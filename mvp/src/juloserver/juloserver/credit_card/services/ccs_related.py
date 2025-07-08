from __future__ import unicode_literals

import logging
from django.db import transaction
from django.db.models import Count

from juloserver.credit_card.models import (
    CreditCard,
    CreditCardApplication,
    CreditCardApplicationHistory,
    CreditCardStatus,
)
from juloserver.credit_card.services.registration_related import (
    update_card_application_history,
)
from juloserver.credit_card.clients import get_bss_credit_card_client
from juloserver.credit_card.constants import CreditCardStatusConstant
from juloserver.credit_card.exceptions import (
    CreditCardApplicationNotFound,
    CreditCardNotFound,
    CreditCardApplicationHasCardNumber,
    CardNumberNotAvailable,
)

from juloserver.account.models import AccountLimit
from juloserver.julo.models import (
    Image,
    WorkflowStatusPath,
    StatusLookup,
    ChangeReason
)
from juloserver.julo.constants import WorkflowConst
from juloserver.julo.statuses import CreditCardCodes
from juloserver.julo.exceptions import JuloException

logger = logging.getLogger(__name__)


def change_status_520(credit_card_application_id, user,
                      note_text, change_reason):
    card_application = CreditCardApplication.objects.filter(
        pk=credit_card_application_id
    ).last()
    card_application_status = CreditCardCodes.CARD_VERIFICATION_SUCCESS
    credit_card = CreditCard.objects.filter(
        credit_card_application=card_application
    ).last()
    if not credit_card:
        raise JuloException("haven't assign card number to Julo card")

    update_card_application_history(
        card_application.id,
        card_application.status.status_code,
        card_application_status,
        change_reason,
        None,
        note_text,
        user.id,
    )

    return card_application_status


def change_status_530(credit_card_application_id, shipping_code, user,
                      note_text, expedition_company, change_reason):
    card_application = CreditCardApplication.objects.filter(
        pk=credit_card_application_id
    ).last()
    card_application_status = card_application.status.status_code

    if shipping_code:
        if card_application_status == CreditCardCodes.CARD_VERIFICATION_SUCCESS:
            card_application.update_safely(
                shipping_number=shipping_code,
                expedition_company=expedition_company,
            )
            card_application_status = CreditCardCodes.CARD_ON_SHIPPING

            update_card_application_history(
                card_application.id,
                card_application.status.status_code,
                card_application_status,
                change_reason,
                None,
                note_text,
                user.id,
            )

    return card_application_status


def change_status_525(credit_card_application_id, user,
                      note_text, change_reason):
    card_application = CreditCardApplication.objects.filter(
        pk=credit_card_application_id
    ).last()
    card_application_status = CreditCardCodes.CARD_APPLICATION_REJECTED
    update_card_application_history(
        card_application.id,
        card_application.status.status_code,
        card_application_status,
        change_reason,
        None,
        note_text,
        user.id,
    )

    return card_application_status


def change_status_523(credit_card_application_id, user,
                      note_text, change_reason):
    card_application = CreditCardApplication.objects.filter(
        pk=credit_card_application_id
    ).last()
    card_application_status = CreditCardCodes.RESUBMIT_SELFIE

    card_resubmit_selfie_history = CreditCardApplicationHistory.objects.filter(
        status_new_id=card_application_status,
        credit_card_application=card_application,
    ).count()
    if card_resubmit_selfie_history < 3:
        update_card_application_history(
            card_application.id,
            card_application.status.status_code,
            card_application_status,
            change_reason,
            None,
            note_text,
            user.id,
        )
    else:
        update_card_application_history(
            card_application.id,
            card_application.status.status_code,
            card_application_status,
            change_reason,
            None,
            note_text,
            user.id,
        )
        update_card_application_history(
            card_application.id,
            card_application_status,
            CreditCardCodes.CARD_APPLICATION_REJECTED,
            change_reason,
        )

        card_application_status = CreditCardCodes.CARD_APPLICATION_REJECTED

    return card_application_status


def change_status_580(credit_card_application_id, user,
                      note_text, change_reason):
    card_application = CreditCardApplication.objects.filter(
        pk=credit_card_application_id
    ).last()
    card_application_status = CreditCardCodes.CARD_ACTIVATED
    update_card_application_history(
        card_application.id,
        card_application.status.status_code,
        card_application_status,
        change_reason,
        None,
        note_text,
        user.id,
    )

    return card_application_status


def change_status_581(credit_card_application_id, user, note_text,
                      block_reason, change_reason):
    card_application = CreditCardApplication.objects.filter(
        pk=credit_card_application_id
    ).last()
    card_application_status = CreditCardCodes.CARD_BLOCKED

    update_card_application_history(
        card_application.id,
        card_application.status.status_code,
        card_application_status,
        change_reason,
        block_reason,
        note_text,
        user.id,
    )

    return card_application_status


def change_status_582(credit_card_application_id, user,
                      note_text, change_reason):
    card_application = CreditCardApplication.objects.filter(
        pk=credit_card_application_id
    ).last()
    card_application_status = CreditCardCodes.CARD_UNBLOCKED
    update_card_application_history(
        card_application.id,
        card_application.status.status_code,
        card_application_status,
        change_reason,
        None,
        note_text,
        user.id,
    )

    return card_application_status


def change_status_583(credit_card_application_id, user,
                      note_text, change_reason):
    card_application = CreditCardApplication.objects.filter(
        pk=credit_card_application_id,
        status_id=CreditCardCodes.CARD_BLOCKED,
    ).last()
    if not card_application:
        return
    credit_card = card_application.creditcard_set.last()
    application = card_application.account.last_application
    bss_credit_card_client = get_bss_credit_card_client()
    response = bss_credit_card_client.close_card(
        credit_card.card_number,
        card_application.virtual_account_number,
        card_application.virtual_card_name,
        application.application_xid
    )
    if 'error' in response or response['responseCode'] != '00':
        return
    card_application_status = CreditCardCodes.CARD_CLOSED
    update_card_application_history(
        card_application.id,
        card_application.status.status_code,
        card_application_status,
        change_reason,
        None,
        note_text,
        user.id,
    )

    return card_application_status


def card_status_change(credit_card_application_id, next_status, change_reason, user,
                       shipping_code, note_text, expedition_company, block_reason):
    credit_card_application = CreditCardApplication.objects\
        .filter(id=credit_card_application_id).last()
    if credit_card_application:
        workflow = WorkflowStatusPath.objects \
            .filter(status_previous=credit_card_application.status.status_code,
                    status_next=next_status,
                    workflow__name=WorkflowConst.CREDIT_CARD).exists()

        if workflow:
            if next_status == CreditCardCodes.CARD_VERIFICATION_SUCCESS:
                return change_status_520(credit_card_application_id, user,
                                         note_text, change_reason)
            elif next_status == CreditCardCodes.CARD_ON_SHIPPING:
                return change_status_530(credit_card_application_id, shipping_code, user,
                                         note_text, expedition_company, change_reason)
            elif next_status == CreditCardCodes.CARD_APPLICATION_REJECTED:
                return change_status_525(credit_card_application_id, user,
                                         note_text, change_reason)
            elif next_status == CreditCardCodes.RESUBMIT_SELFIE:
                return change_status_523(credit_card_application_id, user,
                                         note_text, change_reason)
            elif next_status == CreditCardCodes.CARD_ACTIVATED:
                return change_status_580(credit_card_application_id, user,
                                         note_text, change_reason)
            elif next_status == CreditCardCodes.CARD_BLOCKED:
                return change_status_581(credit_card_application_id, user,
                                         note_text, block_reason, change_reason)
            elif next_status == CreditCardCodes.CARD_UNBLOCKED:
                return change_status_582(credit_card_application_id, user,
                                         note_text, change_reason)
            elif next_status == CreditCardCodes.CARD_CLOSED:
                return change_status_583(credit_card_application_id, user,
                                         note_text, change_reason)

    return False


def data_bucket():
    status_code_total = CreditCardApplication.objects.all()\
        .values('status').annotate(total=Count('id')).order_by('status')

    if status_code_total:
        status_code_data = {}
        for status in CreditCardCodes.all_card_statuses():
            status_code = status_code_total\
                .filter(status=status).last()
            status_total = 0
            if status_code:
                status_total = status_code.get('total')

            status_code_data[status] = status_total

        return status_code_data

    return False


def credit_card_app_list(data):
    status = data.get('type')
    filter_ = {
        'status_id__in': CreditCardCodes.all_card_statuses()
    }
    if status:
        status_lookup = StatusLookup.objects\
            .filter(status_code__gt=500, status_code=status).last()
        if not status_lookup:
            return
        filter_['status'] = status_lookup
        del filter_['status_id__in']

    order = data['order']
    last_id = data['last_id']
    limit = data['limit']
    application_id = data['application_id']
    fullname = data['fullname']
    cc_number = data['card_number']
    va_number = data['va_number']
    credit_card_application_id = data['credit_card_application_id']
    mobile_phone_number = data['mobile_phone_number']
    email = data['email']

    if application_id:
        filter_['account__application__id'] = application_id

    if fullname:
        filter_['virtual_card_name__iexact'] = fullname

    if va_number:
        filter_['virtual_account_number'] = va_number

    if credit_card_application_id:
        filter_['id'] = credit_card_application_id

    if mobile_phone_number:
        filter_['account__application__mobile_phone_1'] = mobile_phone_number

    if email:
        filter_['account__application__email'] = email

    order_by = '-id'
    if order == "desc":
        if last_id > 0:
            filter_['id__lt'] = last_id
    elif order == "asc":
        order_by = 'id'
        if last_id > 0:
            filter_['id__gt'] = last_id

    credit_list = CreditCardApplication.objects\
        .select_related('status').prefetch_related('account__application_set').filter(**filter_)\
        .order_by(order_by)[:limit]

    last_credit = CreditCardApplication.objects\
        .filter(**filter_)\
        .order_by(order_by)\
        .values('id').last()

    items = []
    for crd_list in credit_list:
        filters_ = dict(
            credit_card_application=crd_list
        )
        if cc_number:
            filters_['card_number'] = cc_number

        credit_card = CreditCard.objects\
            .filter(**filters_).values('card_number').last()
        card_number = 0
        if credit_card:
            card_number = credit_card['card_number']

        if not credit_card and cc_number:
            continue

        application = crd_list.account.last_application
        app_obj = {
            'credit_card_application_id': crd_list.id,
            'fullname': crd_list.virtual_card_name,
            'card_number': card_number,
            'va_number': crd_list.virtual_account_number,
            'cdate': crd_list.cdate,
            'udate': crd_list.udate,
            'status': crd_list.status.status_code,
            'application_id': application.id,
            'mobile_phone_number': application.mobile_phone_1,
            'email': application.email,
        }
        last_id = crd_list.id
        items.append(app_obj)

    if last_credit:
        if last_id == last_credit['id']:
            last_id = 0

    credit_lst = {'items': items, 'last_id': last_id}

    return credit_lst


def credit_card_app_details(credit_card_application_id):
    credit_card_application = CreditCardApplication.objects\
        .filter(id=credit_card_application_id).select_related('address').last()

    if credit_card_application:
        credit_app_detail = {}

        credit_card = CreditCard.objects\
            .filter(credit_card_application=credit_card_application).last()
        card_number = 0
        if credit_card:
            card_number = credit_card.card_number

        application = credit_card_application.account.last_application
        customer = credit_card_application.account.customer
        account_limit = AccountLimit\
            .objects.filter(account=credit_card_application.account).last()
        images = Image.objects\
            .filter(image_source=application.id,
                    image_status__in=[Image.CURRENT, Image.RESUBMISSION_REQ])
        image_collection = []
        for image in images:
            image_obj = {
                'type': image.image_type,
                'url': image.image_url,
                'ext': image.image_ext
            }
            image_collection.append(image_obj)

        workflow = WorkflowStatusPath.objects\
            .filter(status_previous=credit_card_application.status.status_code,
                    workflow__name=WorkflowConst.CREDIT_CARD).values('status_next')
        status_lookup = StatusLookup.objects.filter(status_code__in=workflow)\
            .values('status_code', 'status')
        address = credit_card_application.address

        actions = []
        for status in status_lookup:
            code = status['status_code']
            state = status['status']
            change_reason = []
            reasons = ChangeReason.objects.filter(status=status['status_code'])
            if reasons:
                for reason in reasons:
                    change_reason.append(reason.reason)
            else:
                change_reason.append(state)

            status_detail = {'status_code': code,
                             'status': state,
                             'change_reason': change_reason
                             }
            actions.append(status_detail)

        credit_app_detail['credit_card_application_id'] = credit_card_application.id
        credit_app_detail['status'] = credit_card_application.status.status_code
        credit_app_detail['fullname'] = credit_card_application.virtual_card_name
        credit_app_detail['application_id'] = application.id
        credit_app_detail['card_number'] = card_number
        credit_app_detail['va_number'] = credit_card_application.virtual_account_number
        credit_app_detail['application_address'] = application.complete_addresses
        credit_app_detail['dob'] = application.dob
        credit_app_detail['mother_maiden_name'] = customer.mother_maiden_name
        credit_app_detail['bank_name'] = application.bank_name
        credit_app_detail['name_in_bank'] = application.name_in_bank
        credit_app_detail['bank_account_number'] = application.bank_account_number
        credit_app_detail['credit_limit'] = account_limit.max_limit
        credit_app_detail['mobile_phone_number'] = application.mobile_phone_1
        credit_app_detail['email'] = application.email
        credit_app_detail['images'] = image_collection
        credit_app_detail['actions'] = actions
        credit_app_detail["shipping_number"] = credit_card_application.shipping_number
        credit_app_detail['expedition_company'] = credit_card_application.expedition_company
        credit_app_detail["shipping_address"] = {
            "full_address": address.full_address,
            "province": address.provinsi,
            "city": address.kabupaten,
            "district": address.kecamatan,
            "sub_district": address.kelurahan,
            "detail": address.detail,
            "postal_code": address.kodepos
        }

        return credit_app_detail

    return False


@transaction.atomic()
def assign_card(card_number: str, credit_card_application_id: int) -> None:
    credit_card = CreditCard.objects.select_for_update().filter(
        card_number=card_number,
    ).last()

    if not credit_card:
        raise CreditCardNotFound

    if credit_card.credit_card_application:
        raise CardNumberNotAvailable

    credit_card_application = CreditCardApplication.objects.get_or_none(
        pk=credit_card_application_id
    )
    if not credit_card_application:
        raise CreditCardApplicationNotFound

    existing_credit_card = credit_card_application.creditcard_set.last()
    if existing_credit_card and \
            existing_credit_card.credit_card_status.description != CreditCardStatusConstant.CLOSED:
        raise CreditCardApplicationHasCardNumber

    credit_card_status = CreditCardStatus.objects.filter(
        description=CreditCardStatusConstant.ASSIGNED
    ).last()

    credit_card.update_safely(
        credit_card_application=credit_card_application,
        credit_card_status=credit_card_status
    )
