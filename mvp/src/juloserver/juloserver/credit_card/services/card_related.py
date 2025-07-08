from typing import Union
from datetime import timedelta
from dateutil.relativedelta import relativedelta

from django.db import transaction
from django.contrib.auth.models import User
from django.utils import timezone
from django.conf import settings

from juloserver.account.models import Account

from juloserver.credit_card.models import (
    CreditCardApplication,
    CreditCard,
    CreditCardStatus,
    JuloCardWhitelistUser,
    CreditCardApplicationHistory,
)
from juloserver.credit_card.clients import get_bss_credit_card_client
from juloserver.credit_card.constants import (
    CreditCardStatusConstant,
    BSSResponseConstant,
    FeatureNameConst,
)
from juloserver.credit_card.exceptions import (
    CreditCardNotFound,
    FailedResponseBssApiError,
    IncorrectOTP,
)
from juloserver.credit_card.tasks.notification_tasks import (
    send_pn_status_changed,
    send_pn_incorrect_pin_warning,
)

from juloserver.julo.statuses import CreditCardCodes
from juloserver.julo.models import (
    OtpRequest,
    FeatureSetting,
    StatusLookup,
)
from juloserver.julo.services2 import get_redis_client
from juloserver.julo.utils import execute_after_transaction_safely

from juloserver.moengage.services.use_cases import (
    send_event_moengage_for_julo_card_status_change_event,
)


def get_credit_card_information(account: Account) -> Union[dict, None]:
    credit_card_application = CreditCardApplication.objects.only(
        'virtual_account_number', 'virtual_card_name', 'shipping_number', 'address',
        'address__provinsi', 'address__kabupaten', 'address__kecamatan', 'address__kelurahan',
        'address__detail', 'address__kodepos', 'address__latitude', 'address__longitude',
        'expedition_company',
    ).select_related(
        'address',
    ).filter(account=account).last()
    if not credit_card_application:
        return None
    address = credit_card_application.address
    card_information = {
        "virtual_account_number": credit_card_application.virtual_account_number,
        "virtual_card_name": credit_card_application.virtual_card_name,
        "shipping_address": {
            "full_address": address.full_address,
            "province": address.provinsi,
            "city": address.kabupaten,
            "district": address.kecamatan,
            "sub_district": address.kelurahan,
            "detail": address.detail,
        },
        "shipping_number": credit_card_application.shipping_number,
        "expedition_company": credit_card_application.expedition_company,
        "shipping_lang": credit_card_application.address.latitude,
        "shipping_long": credit_card_application.address.longitude,
        "estimated_date": None,
    }

    credit_card = credit_card_application.creditcard_set.last()
    if credit_card:
        card_information['card_number'] = credit_card.card_number
        card_information['card_exp_date'] = credit_card.expired_date

    if credit_card_application.status_id >= CreditCardCodes.CARD_ON_SHIPPING:
        credit_card_application_history = \
            credit_card_application.creditcardapplicationhistory_set.filter(
                status_new=CreditCardCodes.CARD_ON_SHIPPING
            ).last()
        estimated_date = credit_card_application_history.cdate.date() + timedelta(days=7)
        card_information["estimated_date"] = estimated_date

    return card_information


def get_credit_card_application_status(account: Account) -> Union[dict, None]:
    credit_card_application = CreditCardApplication.objects.only(
        'status_id', 'virtual_account_number', 'virtual_card_name',
        'account', 'account__credit_card_status'
    ).select_related('account').filter(
        account=account
    ).last()
    if not credit_card_application:
        return None
    credit_card = credit_card_application.creditcard_set.only('card_number').last()
    status = credit_card_application.status_id
    application = credit_card_application.account.last_application
    redis_client = get_redis_client()
    incorrect_pin_counter_key = 'julo_card:incorrect_pin_counter:{}'.format(
        credit_card_application.virtual_account_number
    )
    incorrect_pin_counter = redis_client.get(incorrect_pin_counter_key)
    incorrect_pin_warning_message = None
    today_datetime = timezone.localtime(timezone.now())
    tomorrow_datetime = today_datetime + relativedelta(days=1, hour=0, minute=0,
                                                       second=0)
    if credit_card and status >= CreditCardCodes.CARD_ACTIVATED:
        bss_credit_card_client = get_bss_credit_card_client()
        response = bss_credit_card_client.inquiry_card_status(
            credit_card.card_number, credit_card_application.virtual_account_number,
            credit_card_application.virtual_card_name, application.application_xid
        )
        if 'error' not in response and response["responseCode"] == '00':
            new_card_status = mapping_credit_card_application_status(response, status)
            if status != new_card_status:
                update_card_application_history(
                    credit_card_application.id, credit_card_application.status_id,
                    new_card_status, 'change by system'
                )

                status = new_card_status
            if response['incorrectPinCounter'].isnumeric():
                incorrect_pin_counter = int(response['incorrectPinCounter'])
                redis_client.set(incorrect_pin_counter_key, incorrect_pin_counter,
                                 tomorrow_datetime - today_datetime)

    if incorrect_pin_counter and int(incorrect_pin_counter) == 2:
        sent_pn_incorrect_pin_warning_key = 'julo_card:sent_pn_incorrect_pin_warning:{}'.format(
            credit_card_application.virtual_account_number
        )
        sent_pn_incorrect_pin_warning = redis_client.get(sent_pn_incorrect_pin_warning_key)
        if sent_pn_incorrect_pin_warning != '1':
            redis_client.set(sent_pn_incorrect_pin_warning_key, 1,
                             tomorrow_datetime - today_datetime)
            send_pn_incorrect_pin_warning.delay(credit_card_application.account.customer.id)
        incorrect_pin_warning_message = 'Kamu sudah salah pin 2x, mohon berhati hati '\
                                        'bila salah sekali akan terblokir otomatis'
    card_status = {
        "status": status,
        "incorrect_pin_warning_message": incorrect_pin_warning_message
    }
    return card_status


def mapping_credit_card_application_status(response: dict, current_card_status_code: int) -> int:
    credit_card_application_status = current_card_status_code
    if response['cardStatus'] == "ACTIVE" and not response['blockStatus'] and \
            not response['dateBlocked'] and not response['dateClosed']:
        credit_card_application_status = CreditCardCodes.CARD_ACTIVATED
    elif response['blockStatus'] and int(response['incorrectPinCounter']) < 3 and \
            response['dateBlocked'] and not response['dateClosed'] and \
            current_card_status_code != CreditCardCodes.CARD_UNBLOCKED:
        credit_card_application_status = CreditCardCodes.CARD_BLOCKED
    elif response['blockStatus'] and int(response['incorrectPinCounter']) >= 3 and \
            response['dateBlocked'] and not response['dateClosed']:
        credit_card_application_status = CreditCardCodes.CARD_BLOCKED_WRONG_PIN
    elif response['cardStatus'] == "CLOSED" and response['dateClosed']:
        credit_card_application_status = CreditCardCodes.CARD_CLOSED

    return credit_card_application_status


def change_pin_credit_card(
        credit_card: CreditCard, old_pin: str, new_pin: str
) -> dict:
    credit_card_application = credit_card.credit_card_application
    application = credit_card_application.account.last_application
    bss_credit_card_client = get_bss_credit_card_client()
    response = bss_credit_card_client.change_pin(
        credit_card.card_number,
        credit_card_application.virtual_account_number,
        credit_card_application.virtual_card_name,
        old_pin,
        new_pin,
        application.application_xid
    )

    return response


def block_card(credit_card_application, block_reason, block_from_ccs=False):
    bss_credit_card_client = get_bss_credit_card_client()
    credit_card = credit_card_application.creditcard_set.only('card_number').last()
    application = credit_card_application.account.last_application
    response = bss_credit_card_client.block_card(
        credit_card.card_number, credit_card_application.virtual_account_number,
        credit_card_application.virtual_card_name, application.application_xid
    )
    if 'error' not in response and response["responseCode"] == '00' and not block_from_ccs:
        update_card_application_history(
            credit_card_application.id, credit_card_application.status_id,
            CreditCardCodes.CARD_BLOCKED, 'change by system', block_reason
        )
    elif 'error' in response:
        raise Exception(response['error'])
    elif response["responseCode"] != '00':
        raise Exception(response['responseDescription'])


@transaction.atomic
def unblock_card(account: Account, pin: str) -> None:
    credit_card = CreditCard.objects.select_related(
        'credit_card_application',
    ).select_for_update().filter(
        credit_card_application__isnull=False,
        credit_card_application__account=account,
        credit_card_application__status=CreditCardCodes.CARD_UNBLOCKED,
    ).last()
    if not credit_card:
        raise CreditCardNotFound

    bss_credit_card_client = get_bss_credit_card_client()
    credit_card_application = credit_card.credit_card_application
    application = credit_card_application.account.last_application
    response = bss_credit_card_client.unblock_card(
        credit_card.card_number,
        credit_card_application.virtual_account_number,
        credit_card_application.virtual_card_name,
        pin,
        application.application_xid
    )
    if 'error' in response or \
            response['responseCode'] != BSSResponseConstant.TRANSACTION_SUCCESS['code']:
        raise FailedResponseBssApiError
    update_card_application_history(
        credit_card_application.id,
        credit_card_application.status.status_code,
        CreditCardCodes.CARD_ACTIVATED,
        'change by user'
    )


def reset_pin_credit_card(account: Account, pin: str, otp: str) -> None:
    credit_card = CreditCard.objects.select_related(
        'credit_card_application',
    ).filter(
        credit_card_application__isnull=False,
        credit_card_application__account=account,
    ).last()
    if not credit_card or \
            credit_card.credit_card_application.status_id == CreditCardCodes.CARD_BLOCKED:
        raise CreditCardNotFound

    otp_request = OtpRequest.objects.filter(
        otp_token=otp, customer=account.customer, is_used=False
    ).last()
    if not otp_request:
        raise IncorrectOTP

    bss_credit_card_client = get_bss_credit_card_client()
    credit_card_application = credit_card.credit_card_application
    application = credit_card_application.account.last_application
    response = bss_credit_card_client.reset_pin(
        credit_card.card_number,
        credit_card_application.virtual_account_number,
        credit_card_application.virtual_card_name,
        otp,
        pin,
        application.application_xid
    )
    if 'error' in response or \
            response['responseCode'] != BSSResponseConstant.TRANSACTION_SUCCESS['code']:
        raise FailedResponseBssApiError
    otp_request.update_safely(is_used=True)
    if credit_card_application.status_id == CreditCardCodes.CARD_BLOCKED_WRONG_PIN:
        card_application_history = credit_card_application.creditcardapplicationhistory_set.filter(
            status_new_id=CreditCardCodes.CARD_BLOCKED_WRONG_PIN
        ).last()
        new_card_status_code = CreditCardCodes.CARD_ACTIVATED
        if card_application_history.status_old_id == CreditCardCodes.CARD_UNBLOCKED:
            new_card_status_code = CreditCardCodes.CARD_UNBLOCKED
        update_card_application_history(
            credit_card_application.id,
            credit_card_application.status_id,
            new_card_status_code,
            'change by system'
        )
    redis_client = get_redis_client()
    today_datetime = timezone.localtime(timezone.now())
    tomorrow_datetime = today_datetime + relativedelta(days=1, hour=0, minute=0,
                                                       second=0)
    sent_pn_incorrect_pin_warning_key = 'julo_card:sent_pn_incorrect_pin_warning:{}'.format(
        credit_card_application.virtual_account_number
    )
    redis_client.set(sent_pn_incorrect_pin_warning_key, 0,
                     tomorrow_datetime - today_datetime)


def is_julo_card_whitelist_user(application_id: int) -> bool:
    """
    check if the user in whitelist.
    if the feature setting is off meaning we don't use table ops.julo_card_whitelist_user to filter
    customer whitelist so in that case, all customers can pass whitelist

    :param application_id: integer application id
    :return: boolean
    """
    feature_setting = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.JULO_CARD_WHITELIST,
        is_active=True
    ).last()
    if not feature_setting:
        return True

    return JuloCardWhitelistUser.objects.filter(
        application_id=application_id
    ).exists()


def get_credit_card_status(credit_card_application_code: int) -> Union[CreditCardStatus, None]:
    card_status_description = None
    if credit_card_application_code == CreditCardCodes.CARD_ACTIVATED:
        card_status_description = CreditCardStatusConstant.ACTIVE
    elif credit_card_application_code == CreditCardCodes.CARD_BLOCKED:
        card_status_description = CreditCardStatusConstant.BLOCKED
    elif credit_card_application_code == CreditCardCodes.CARD_CLOSED:
        card_status_description = CreditCardStatusConstant.CLOSED

    if not card_status_description:
        return None

    credit_card_status = CreditCardStatus.objects.filter(
        description=card_status_description
    ).last()

    return credit_card_status


@transaction.atomic
def update_card_application_history(credit_card_application_id, old_status, new_status,
                                    change_reason, block_reason=None, note_text=None, user_id=None):
    from juloserver.credit_card.tasks.credit_card_tasks import update_card_application_note

    old_status_lookup = StatusLookup.objects.filter(
        status_code=old_status).last()
    new_status_lookup = StatusLookup.objects.filter(
        status_code=new_status).last()
    credit_card_application = CreditCardApplication.objects.filter(
        pk=credit_card_application_id).last()
    credit_card_application.update_safely(status=new_status_lookup)
    account = credit_card_application.account
    user = User.objects.filter(pk=user_id).last()

    credit_card_history = CreditCardApplicationHistory.objects.create(
        status_old=old_status_lookup,
        status_new=new_status_lookup,
        change_reason=change_reason,
        changed_by=user,
        credit_card_application=credit_card_application,
        block_reason=block_reason,
    )
    account.update_safely(
        credit_card_status=new_status_lookup.status_code
    )
    credit_card = credit_card_application.creditcard_set.last()
    if credit_card:
        credit_card_status = get_credit_card_status(new_status)
        if credit_card_status:
            credit_card.update_safely(
                credit_card_status=credit_card_status,
            )

    if note_text:
        update_card_application_note.delay(
            credit_card_application_id,
            user_id,
            note_text,
            credit_card_history.id
        )
    send_pn_status_changed.delay(account.customer.id, new_status)
    execute_after_transaction_safely(
        lambda: send_event_moengage_for_julo_card_status_change_event.apply_async(
            (credit_card_history.id,),
            countdown=settings.DELAY_FOR_REALTIME_EVENTS,
        )
    )
