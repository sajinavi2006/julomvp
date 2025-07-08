from django.conf import settings

from juloserver.moengage.constants import MoengageEventType
from juloserver.moengage.models import MoengageUpload
from juloserver.moengage.services.data_constructors import (
    construct_data_for_payment_received_event,
    construct_user_attributes_for_realtime_basis,
    construct_data_for_autodebit_failed_deduction,
    construct_data_for_autodebet_payment_method_disabled,
    construct_data_for_activated_autodebet,
    construct_data_for_autodebet_bri_expiration_handler,
    construct_data_for_activated_oneklik,
)
from juloserver.moengage.services.use_cases import send_to_moengage
import logging

from juloserver.moengage.utils import exception_captured

logger = logging.getLogger(__name__)


def update_moengage_for_payment_received(account_trx):
    customer = account_trx.account.customer
    event_type = MoengageEventType.BE_PAYMENT_RECEIVED
    moengage_upload = MoengageUpload.objects.create(
        type=event_type,
        customer_id=customer.id
    )

    with exception_captured(moengage_upload.id, "construct_data_failed", reraise=False):
        data_to_send = []
        event_data = construct_data_for_payment_received_event(account_trx, event_type)
        data_to_send.append(event_data)

        user_attributes = construct_user_attributes_for_realtime_basis(customer)
        data_to_send.append(user_attributes)
        logger.info({
            'action': 'moengage_event_payment_received',
            'data': data_to_send
        })

        send_to_moengage.apply_async(
            ([moengage_upload.id], data_to_send)
        )


def send_event_autodebit_failed_deduction(account_payment_id, customer, vendor):
    event_type = MoengageEventType.AUTODEBIT_FAILED_DEDUCTION
    moengage_upload = MoengageUpload.objects.create(type=event_type, customer=customer)

    with exception_captured(moengage_upload.id, "construct_data_failed", reraise=False):
        data_to_send = []
        event_data = construct_data_for_autodebit_failed_deduction(
            account_payment_id, customer, vendor, event_type
        )

        if not event_data:
            return

        data_to_send.append(event_data)

        user_attributes = construct_user_attributes_for_realtime_basis(customer)
        data_to_send.append(user_attributes)
        logger.info({'action': 'send_event_autodebit_failed_deduction', 'data': data_to_send})

        send_to_moengage.apply_async(([moengage_upload.id], data_to_send))


def send_event_autodebet_payment_method_disabled(
    customer, vendor, event_type, start_date_time, end_date_time
):
    moengage_upload = MoengageUpload.objects.create(type=event_type, customer_id=customer.id)
    with exception_captured(moengage_upload.id, "construct_data_failed", reraise=False):
        data_to_send = []
        event_data = construct_data_for_autodebet_payment_method_disabled(
            customer, vendor, event_type, start_date_time, end_date_time
        )
        data_to_send.append(event_data)

        user_attributes = construct_user_attributes_for_realtime_basis(customer)
        data_to_send.append(user_attributes)
        logger.info(
            {'action': 'send_event_autodebet_payment_method_disabled', 'data': data_to_send}
        )

        send_to_moengage.apply_async(([moengage_upload.id], data_to_send))


def send_event_activated_autodebet(customer, event_type, payday, vendor, next_due):
    moengage_upload = MoengageUpload.objects.create(type=event_type, customer_id=customer.id)
    with exception_captured(moengage_upload.id, "construct_data_failed", reraise=False):
        data_to_send = []
        event_data = construct_data_for_activated_autodebet(
            customer, event_type, payday, vendor, next_due
        )
        data_to_send.append(event_data)

        user_attributes = construct_user_attributes_for_realtime_basis(customer)
        data_to_send.append(user_attributes)
        logger.info({'action': 'send_event_activated_autodebet', 'data': data_to_send})

        send_to_moengage.apply_async(([moengage_upload.id], data_to_send))


def send_event_activated_oneklik(customer, event_type, cdate):
    moengage_upload = MoengageUpload.objects.create(type=event_type, customer_id=customer.id)
    with exception_captured(moengage_upload.id, "construct_data_failed", reraise=False):
        data_to_send = []
        event_data = construct_data_for_activated_oneklik(customer, event_type, cdate)
        data_to_send.append(event_data)

        user_attributes = construct_user_attributes_for_realtime_basis(customer)
        data_to_send.append(user_attributes)
        logger.info({'action': 'send_event_activated_oneklik', 'data': data_to_send})

        send_to_moengage.apply_async(([moengage_upload.id], data_to_send))


def send_event_autodebet_bri_expiration_handler(account_payment_id, customer):
    event_type = MoengageEventType.BE_ADBRI_EXP
    moengage_upload = MoengageUpload.objects.create(type=event_type, customer=customer)

    with exception_captured(moengage_upload.id, "construct_data_failed", reraise=False):
        data_to_send = []
        event_data = construct_data_for_autodebet_bri_expiration_handler(
            account_payment_id, customer, event_type
        )

        if not event_data:
            return

        data_to_send.append(event_data)

        user_attributes = construct_user_attributes_for_realtime_basis(customer)
        data_to_send.append(user_attributes)
        logger.info({'action': 'send_event_autodebet_bri_expiration_handler', 'data': data_to_send})

        send_to_moengage.apply_async(([moengage_upload.id], data_to_send))
