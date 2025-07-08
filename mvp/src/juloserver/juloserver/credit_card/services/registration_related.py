from __future__ import unicode_literals

import logging
import time
import csv
from datetime import timedelta

from django.utils import timezone
from django.template.loader import render_to_string
from django.conf import settings

from juloserver.credit_card.models import (
    CreditCard,
    CreditCardApplication,
    CreditCardMobileContentSetting,
)
from juloserver.julo.statuses import (
    CreditCardCodes,
    JuloOneCodes
)
from juloserver.credit_card.constants import (
    ErrorMessage,
    OTPConstant,
)
from juloserver.credit_card.clients import get_bss_credit_card_client
from juloserver.credit_card.utils import AESCipher
from juloserver.credit_card.services.card_related import (
    is_julo_card_whitelist_user,
    update_card_application_history,
)
from juloserver.credit_card.tasks.notification_tasks import (
    send_pn_inform_first_transaction_cashback,
)

from juloserver.julo.constants import (
    FeatureNameConst,
    ApplicationStatusCodes
)
from juloserver.julo.models import (
    Image,
    StatusLookup,
    OtpRequest,
    MobileFeatureSetting,
    FeatureSetting,
    Customer,
    Document
)
from juloserver.julo.tasks import send_sms_otp_token, upload_image
from juloserver.julo.exceptions import JuloException

from juloserver.loan_refinancing.templatetags.format_date import format_date_to_locale_format
from juloserver.account.models import (
    Account,
    Address
)
from datetime import date
from juloserver.credit_card.tasks import (
    generate_customer_tnc_agreement,
    upload_credit_card
)

from juloserver.otp.constants import (
    OTPType,
    OTPRequestStatus,
)
from juloserver.otp.services import (
    get_otp_feature_setting,
    get_resend_time_by_otp_type,
    check_otp_request_is_active,
    get_total_retries_and_start_create_time,
    is_change_sms_provider,
)

from juloserver.promo.models import PromoCode

logger = logging.getLogger(__name__)


def card_stock_check():
    return CreditCard.objects \
        .select_related('credit_card_status') \
        .filter(credit_card_status__description='unassigned') \
        .exists()


def credit_card_tnc(customer_id):
    mobile_content_setting = CreditCardMobileContentSetting.objects \
        .filter(content_name='Credit Card TNC', is_active=True) \
        .last()

    if not mobile_content_setting:
        return False

    if len(mobile_content_setting.content) == 0:
        return False

    feature_setting = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.CREDIT_CARD,
        is_active=True).last()

    if not feature_setting:
        return False

    parameters = feature_setting.parameters
    customer_name = parameters['customer_name']
    customer = Customer.objects.get_or_none(pk=customer_id)
    if not customer:
        return False

    if customer.fullname:
        customer_name = customer.fullname

    today = date.today()
    date_now = format_date_to_locale_format(today)

    tnc_content = mobile_content_setting.content
    tnc_content_replaced = tnc_content.format(
        card_name=parameters['card_name'],
        customer_name='{' + customer_name + '}',
        julo_email=parameters['julo_email'],
        current_date=date_now
    )

    return tnc_content_replaced


def card_requests(customer_id, data):
    account = Account.objects \
        .select_related('customer') \
        .filter(customer=customer_id) \
        .last()
    if not account:
        return False

    application = account.last_application
    if not application:
        return False

    if not is_eligible_register_julo_card(application):
        return False

    image_selfie = data['image_selfie']
    submit_selfie = submit_selfie_image(image_selfie, application.id, 'credit_card_selfie')
    if not submit_selfie:
        return False

    latitude = data['latitude']
    longitude = data['longitude']
    provinsi = data['provinsi']
    kabupaten = data['kabupaten']
    kecamatan = data['kecamatan']
    kelurahan = data['kelurahan']
    kodepos = data['kodepos']
    address_detail = data['address_detail']

    address = Address.objects.create(
        latitude=latitude,
        longitude=longitude,
        provinsi=provinsi,
        kabupaten=kabupaten,
        kecamatan=kecamatan,
        kelurahan=kelurahan,
        kodepos=kodepos,
        detail=address_detail
    )

    if not address:
        return False

    card_application_status = CreditCardCodes.CARD_APPLICATION_SUBMITTED

    status_lookup = StatusLookup.objects.filter(
        status_code=card_application_status).last()
    va_number = create_va_number()
    card_application = CreditCardApplication.objects.create(
        virtual_card_name=application.full_name_only,
        virtual_account_number=va_number,
        status=status_lookup,
        address=address,
        account=account,
        image=submit_selfie
    )

    if not card_application:
        return False

    task_param = [
        card_application.id,
        0,
        card_application_status,
        'customer_triggered'
    ]
    update_card_application_history(*task_param)
    return True


def create_va_number():
    credit_card_application = CreditCardApplication.objects.filter(
        virtual_account_number__istartswith=settings.BSS_JULO_CARD_VA_PREFIX).last()
    if not credit_card_application:
        first_zeroes = '0'.zfill(11)
        va_number = settings.BSS_JULO_CARD_VA_PREFIX + first_zeroes
        return va_number

    va_number = int(credit_card_application.virtual_account_number) + 1
    return str(va_number)


def application_eligible_credit_card(application, account):
    if not application.is_julo_one() or \
            application.status != ApplicationStatusCodes.LOC_APPROVED:
        return False

    if account.status.status_code != JuloOneCodes.ACTIVE:
        return False

    return True


def card_stock_eligibility(customer_id):
    account = Account.objects \
        .select_related('customer') \
        .filter(customer=customer_id) \
        .last()
    if not account:
        return False

    application = account.last_application
    if not application:
        return False

    if not application_eligible_credit_card(application, account):
        return False

    return True


def image_resubmission(image, credit_card_application):
    account = credit_card_application.account
    if not account:
        return False

    application = account.last_application
    if not application:
        return False

    if not application_eligible_credit_card(application, account):
        return False

    submit_selfie = submit_selfie_image(image, application.id, 'credit_card_selfie')
    if not submit_selfie:
        return False

    credit_card_application.update_safely(
        image=submit_selfie
    )

    return True


def submit_selfie_image(image, application, image_type, oss_upload=True):
    new_image = Image()
    new_image.image_type = image_type
    new_image.image_source = application
    new_image.save()
    new_image.image.save(new_image.full_image_name(image.name), image)

    if oss_upload:
        upload_image.apply_async((new_image.id, False,), queue='high', routing_key='high')
    return new_image


def credit_card_confirmation(account) -> None:
    credit_card_application = CreditCardApplication.objects.filter(account=account).last()
    update_card_application_history(
        credit_card_application.id, credit_card_application.status_id,
        CreditCardCodes.CARD_RECEIVED_BY_USER, 'customer_triggered'
    )


def activation_card(data: dict, account: Account):
    credit_card_application = CreditCardApplication.objects.only(
        'id', 'virtual_account_number', 'virtual_card_name', 'status', 'account'
    ).filter(account=account, status_id=CreditCardCodes.CARD_VALIDATED).last()

    if not credit_card_application:
        return ErrorMessage.CREDIT_CARD_NOT_FOUND
    credit_card = credit_card_application.creditcard_set.last()
    if not credit_card:
        return ErrorMessage.CREDIT_CARD_NOT_FOUND
    bss_credit_card_client = get_bss_credit_card_client()
    application = credit_card_application.account.last_application
    response = bss_credit_card_client.set_new_pin(
        credit_card.card_number, credit_card_application.virtual_account_number,
        credit_card_application.virtual_card_name, data['otp'], data['pin'],
        application.application_xid
    )
    if 'error' in response or response['responseCode'] != '00':
        return ErrorMessage.FAILED_PROCESS
    otp_request = OtpRequest.objects.filter(
        otp_token=data['otp'], customer=account.customer, is_used=False
    ).last()
    otp_request.update_safely(is_used=True)
    update_card_application_history(
        credit_card_application.id, credit_card_application.status_id,
        CreditCardCodes.CARD_ACTIVATED, 'customer_triggered'
    )
    promo_code = PromoCode.objects.select_related('promo_code_benefit').filter(
        promo_name='JULOCARDCASHBACK',
        promo_code='JULOCARDCASHBACK',
        is_active=True
    ).last()
    if promo_code:
        eta_send_pn = timezone.localtime(timezone.now()) + timedelta(days=1)
        cashback_percentage = promo_code.promo_code_benefit.value.get('percent')
        cashback_max_amount = promo_code.promo_code_benefit.value.get('max_cashback')
        send_pn_inform_first_transaction_cashback.apply_async(
            (credit_card_application.id, cashback_percentage, cashback_max_amount,),
            eta=eta_send_pn
        )


def send_otp(transaction_type, credit_card_application):

    action_type = OTPConstant.ACTION_TYPE.new_pin
    if transaction_type == OTPConstant.TRANSACTION_TYPE.reset_pin:
        action_type = OTPConstant.ACTION_TYPE.reset_pin

    application = credit_card_application.account.last_application
    customer = application.customer
    all_otp_settings = MobileFeatureSetting.objects.get_or_none(
        feature_name='otp_setting'
    )
    otp_setting = get_otp_feature_setting(OTPType.SMS, all_otp_settings)
    otp_wait_seconds = otp_setting['wait_time_seconds']
    otp_max_request = otp_setting['otp_max_request']
    delta_in_seconds = get_resend_time_by_otp_type(OTPType.SMS, otp_setting)
    existing_otp_request = OtpRequest.objects.filter(
        customer=application.customer, action_type=action_type
    ).order_by('id').last()
    current_ts = timezone.localtime(timezone.now())
    retry_count = 1
    data = {
        'resend_time': current_ts + timedelta(seconds=delta_in_seconds),
        'retry_count': retry_count
    }
    change_sms_provider = False
    if existing_otp_request:
        current_count, start_create_ts = get_total_retries_and_start_create_time(
            customer.id, otp_wait_seconds, OTPType.SMS)
        retry_count += current_count
        if retry_count > otp_max_request:
            logger.warning('exceeded the max request, '
                           'customer_id={}, otp_request_id={}, retry_count={}, '
                           'otp_max_request={}'.format(customer.id, existing_otp_request.id,
                                                       retry_count, otp_max_request))

            resend_ts_for_limit_exceed = timezone.localtime(timezone.now())
            if start_create_ts:
                resend_ts_for_limit_exceed = timezone.localtime(
                    start_create_ts
                ) + timedelta(seconds=otp_wait_seconds)

            data['retry_count'] = retry_count
            data['resend_time'] = resend_ts_for_limit_exceed

            return OTPRequestStatus.LIMIT_EXCEEDED, data

        previous_ts = existing_otp_request.cdate
        resend_ts = timezone.localtime(previous_ts) + \
            timedelta(seconds=delta_in_seconds)
        if check_otp_request_is_active(existing_otp_request, otp_wait_seconds, current_ts):
            if current_ts < resend_ts:
                logger.warning('requested OTP less than resend time, '
                               'customer_id={}, otp_request_id={}, current_time={}, '
                               'resend_time={}'.format(customer.id, existing_otp_request.id,
                                                       current_ts, resend_ts))
                data['retry_count'] = retry_count - 1
                data['resend_time'] = resend_ts
                return OTPRequestStatus.RESEND_TIME_INSUFFICIENT, data

        change_sms_provider = is_change_sms_provider(existing_otp_request.sms_history,
                                                     current_ts, resend_ts)
    data['resend_time'] = current_ts + timedelta(seconds=delta_in_seconds)
    data['retry_count'] = retry_count
    bss_credit_card_client = get_bss_credit_card_client()
    credit_card = credit_card_application.creditcard_set.last()
    response = bss_credit_card_client.request_otp_value(
        credit_card.card_number, credit_card_application.virtual_account_number,
        credit_card_application.virtual_card_name, transaction_type, application.application_xid
    )
    if 'error' in response or response['responseCode'] != '00':
        err_msg = (
            "failed to request otp to bss "
            "response: {}".format(
                response
            )
        )
        raise JuloException(err_msg)
    aes_cipher = AESCipher(credit_card.card_number)
    otp_value = aes_cipher.decrypt(response['otpValue'])
    customer = application.customer
    postfixed_request_id = str(customer.id) + str(int(time.time()))
    otp_request = OtpRequest.objects.create(
        customer=customer, request_id=postfixed_request_id,
        otp_token=otp_value, application=application, phone_number=application.mobile_phone_1,
        action_type=action_type, otp_service_type=OTPType.SMS)
    text_message = render_to_string(
        'sms_otp_token_application.txt', context={'otp_token': otp_value})
    send_sms_otp_token.delay(
        application.mobile_phone_1, text_message, customer.id, otp_request.id,
        change_sms_provider
    )

    return OTPRequestStatus.SUCCESS, data


def customer_tnc_created(customer_id):
    account = Account.objects \
        .select_related('customer') \
        .filter(customer=customer_id) \
        .last()
    if not account:
        return False

    application = account.last_application
    if not application:
        return False

    if not application_eligible_credit_card(application, account):
        return False

    generate_customer_tnc_agreement.delay(customer_id)
    return True


def get_customer_tnc(customer_id):
    account = Account.objects \
        .select_related('customer') \
        .filter(customer=customer_id) \
        .last()
    if not account:
        return False

    application = account.last_application
    if not application:
        return False

    if not application_eligible_credit_card(application, account):
        return False

    credit_card_docs = Document.objects.filter(
        document_source=application.id
    ).last()

    if not credit_card_docs:
        return False

    return credit_card_docs.document_url


def data_upload(credit_card_csv):
    reader = csv.DictReader(credit_card_csv.read().decode().splitlines())
    card_data = []
    for line in reader:
        card_number = dict()
        card_number['card_number'] = line['Nomor Kartu']
        card_number['expired_date'] = line['Expired Date (MMYY)']
        card_data.append(card_number)

    upload_credit_card.delay(card_data)

    return card_data


def is_eligible_register_julo_card(application):
    account = application.account
    if not application_eligible_credit_card(application, account):
        return False

    if not is_julo_card_whitelist_user(application.id):
        return False

    card_application = CreditCardApplication.objects.filter(
        account=account
    ).last()

    if card_application and \
            card_application.status_id not in CreditCardCodes.status_eligible_resubmission():
        return False

    return True
