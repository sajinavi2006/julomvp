from __future__ import absolute_import

import logging
from ast import literal_eval
from datetime import datetime, timedelta
from typing import (
    Dict,
    List,
)

from celery import task
from dateutil.relativedelta import relativedelta
from django.utils import timezone

from juloserver.account.models import (
    Account,
    AccountTransaction,
    ExperimentGroup,
)
from juloserver.account_payment.constants import AccountPaymentCons
from juloserver.account_payment.models import OldestUnpaidAccountPayment, AccountPayment
from juloserver.ana_api.models import CustomerSegmentationComms, PdChurnModelResult, QrisFunnelLastLog
from juloserver.email_delivery.constants import EmailStatusMapping
from juloserver.email_delivery.services import update_email_details
from juloserver.julo.clients import get_julo_sentry_client
from juloserver.julo.models import Application, FeatureSetting, SmsHistory, EmailHistory, Customer
from juloserver.julo.services2 import get_redis_client
from juloserver.julo.statuses import LoanStatusCodes
from juloserver.minisquad.constants import (
    RedisKey,
    ExperimentConst,
)
from juloserver.minisquad.services import get_oldest_unpaid_account_payment_ids
from juloserver.minisquad.utils import (
    validate_activate_experiment,
    batch_pk_query_with_cursor,
)
from juloserver.moengage.constants import MAX_EVENT
from juloserver.moengage.constants import MoengageEventType
from juloserver.moengage.constants import (
    PnNotificationStreams,
    SmsStreamsStatus,
    InAppStreamsStatus,
    InstallStreamsStatus,
    OnsiteMessagingStreamsStatus, OnsiteMessagingStreamKeyMapping,
)
from juloserver.moengage.exceptions import MoengageCallbackError
from juloserver.moengage.models import (
    MoengageOsmSubscriber,
    MoengageUploadBatch,
    MoengageCustomerInstallHistory,
)
from juloserver.moengage.services.inapp_notif_services import update_inapp_notif_details
from juloserver.moengage.services.parser import parse_stream_data
from juloserver.moengage.services.pn_services import send_pn_details_from_moengage_streams
from juloserver.moengage.services.sms_services import update_sms_details
from juloserver.moengage.services.use_cases import (
    send_customer_segment_moengage_bulk,
    update_moengage_for_account_status_change,
    update_moengage_for_application_status_change,
    update_moengage_for_loan_status_change,
    update_moengage_for_payment_status_change,
    update_moengage_for_payment_due_amount_change,
    update_moengage_for_refinancing_request_status_change,
    update_moengage_for_scheduled_application_status_change_events,
    data_import_moengage_for_loan_status_change_event,
    bulk_update_moengage_for_scheduled_loan_status_change_210,
    bulk_create_moengage_upload,
    update_moengage_for_loan_status_reminders_event_bulk,
    send_user_attributes_to_moengage_in_bulk_daily,
    send_user_attributes_to_moengage_for_tailor_exp,
    send_user_attributes_to_moengage_for_late_fee_earlier_exp,
    send_churn_users_to_moengage_in_bulk_daily,
    send_qris_master_agreement_data_moengage_bulk,
    send_customer_risk_segment_bulk,
)
from juloserver.moengage.services.use_cases_ext2 import (
    update_moengage_for_payment_received,
    send_event_autodebit_failed_deduction,
    send_event_activated_autodebet,
    send_event_autodebet_bri_expiration_handler,
    send_event_activated_oneklik,
)
from juloserver.moengage.utils import (
    chunks,
    preprocess_moengage_stream,
)
from juloserver.moengage.utils import search_and_remove_postfix_data
from juloserver.pn_delivery.services import update_pn_details
from juloserver.streamlined_communication.models import InAppNotificationHistory
from juloserver.minisquad.constants import REPAYMENT_ASYNC_REPLICA_DB
from juloserver.apiv2.models import PdCollectionModelResult
from django.db.models import F


sentry_client = get_julo_sentry_client()
logger = logging.getLogger(__name__)


@task(name='async_update_moengage_for_application_status_change')
def async_update_moengage_for_application_status_change(application_id, new_status_code):
    update_moengage_for_application_status_change(application_id, new_status_code)


@task(name='async_update_moengage_for_loan_status_change')
def async_update_moengage_for_loan_status_change(loan_id):
    update_moengage_for_loan_status_change(loan_id)


@task(name='async_update_moengage_for_payment_status_change')
def async_update_moengage_for_payment_status_change(payment_id):
    update_moengage_for_payment_status_change(payment_id)


@task(name='async_update_moengage_for_payment_due_amount_change')
def async_update_moengage_for_payment_due_amount_change(payment_id, payment_order=0):
    update_moengage_for_payment_due_amount_change(payment_id, payment_order)


@task(queue='moengage_low')
def async_update_moengage_for_account_status_change(account_status_history_id):
    update_moengage_for_account_status_change(account_status_history_id)


@task(queue='moengage_high')
def async_update_moengage_for_refinancing_request_status_change(loan_refinancing_request_id):
    update_moengage_for_refinancing_request_status_change(loan_refinancing_request_id)


@task(name='trigger_update_moengage_for_scheduled_events')
def trigger_update_moengage_for_scheduled_events():
    moengage_upload_batch_id = bulk_create_moengage_upload()
    update_moengage_for_loan_status_reminders_event_bulk.delay(moengage_upload_batch_id)


@task(queue='moengage_low')
def trigger_update_moengage_for_scheduled_application_status_change_events():
    update_moengage_for_scheduled_application_status_change_events()


@task(queue='moengage_high')
def async_moengage_events_for_j1_loan_status_change(loan_id, loan_status_new):
    loan_status_filter = [LoanStatusCodes.INACTIVE,
                          LoanStatusCodes.LENDER_APPROVAL,
                          LoanStatusCodes.FUND_DISBURSAL_ONGOING,
                          LoanStatusCodes.MANUAL_FUND_DISBURSAL_ONGOING,
                          LoanStatusCodes.TRANSACTION_FAILED,
                          LoanStatusCodes.CANCELLED_BY_CUSTOMER,
                          LoanStatusCodes.SPHP_EXPIRED,
                          LoanStatusCodes.FUND_DISBURSAL_FAILED,
                          LoanStatusCodes.LENDER_REJECT,
                          LoanStatusCodes.CURRENT,
                          LoanStatusCodes.PAID_OFF
                          ]

    if loan_status_new in loan_status_filter:
        data_import_moengage_for_loan_status_change_event(loan_id, loan_status_new)


@task(queue='moengage_low')
def trigger_bulk_update_moengage_for_scheduled_loan_status_change_210():
    bulk_update_moengage_for_scheduled_loan_status_change_210()


@task(queue='moengage_low')
def update_db_using_streams(data):
    events = data['events']
    for data in events:
        event_code = data['event_code']
        if event_code in list(InAppStreamsStatus.keys()):
            stream = parse_stream_data(data, 'INAPP')
            update_inapp_notif_details(stream, is_stream=True)
        elif event_code in list(EmailStatusMapping['MoEngageStream'].keys()):
            stream = parse_stream_data(data, 'EMAIL')
            update_email_details(stream, is_stream=True)
        elif event_code in list(PnNotificationStreams.keys()):
            stream = parse_stream_data(data, 'PN')
            update_pn_details(stream, is_stream=True)
        elif event_code in list(SmsStreamsStatus.keys()):
            stream = parse_stream_data(data, 'SMS')
            update_sms_details(stream, is_stream=True)
        else:
            continue


@task(queue='moengage_high')
def trigger_to_update_data_on_moengage():
    """
    Daily task for updating our customer data in MoEngage side.
    Task execution: juloserver.settings.moengage_upload_celery
    """
    moengage_uploads_customer_ids = Account.objects.distinct().values_list('customer_id', flat=True)
    moengage_upload_batch = MoengageUploadBatch.objects.create(
        type=MoengageEventType.CUSTOMER_DAILY_UPDATE,
        data_count=len(moengage_uploads_customer_ids))

    for customer_list in chunks(moengage_uploads_customer_ids, MAX_EVENT):
        send_user_attributes_to_moengage_in_bulk_daily.delay(
            customer_list, moengage_upload_batch.id)
    moengage_upload_batch.update_safely(status="all_dispatched")


@task(queue='moengage_high')
def trigger_to_push_churn_data_on_moengage():
    """
    Daily task for updating churn users on MoEngage side.
    """
    now = timezone.localtime(timezone.now())
    cutoff_datetime = now - timezone.timedelta(days=1)
    churn_ids = PdChurnModelResult.objects.filter(cdate__gte=cutoff_datetime).values_list('id', flat=True)
    if not churn_ids:
        return
    moengage_upload_batch = MoengageUploadBatch.objects.create(
        type=MoengageEventType.IS_CHURN_EXPERIMENT,
        data_count=len(churn_ids))

    for pchurn_ids in chunks(churn_ids, MAX_EVENT):
        send_churn_users_to_moengage_in_bulk_daily.delay(
            pchurn_ids, moengage_upload_batch.id)
    moengage_upload_batch.update_safely(status="all_dispatched")


@task(queue='moengage_high')
def daily_update_sign_master_agreement_qris():
    """
    Daily update sign Master agreement for qris on MoEngage (ME) in bulk
    """
    now = timezone.localtime(timezone.now())
    cutoff_datetime = now - timezone.timedelta(days=1)
    customer_ids = QrisFunnelLastLog.objects.filter(
        udate__gte=cutoff_datetime,
        customer_id__isnull=False,
        read_master_agreement_date__isnull=False
    ).values_list('customer_id', flat=True)

    moengage_upload_batch = MoengageUploadBatch.objects.create(
        type=MoengageEventType.QRIS_READ_SIGN_MASTER_AGREEMENT,
        data_count=len(customer_ids),
    )
    for ids in chunks(customer_ids, MAX_EVENT):
        send_qris_master_agreement_data_moengage_bulk.delay(
            customer_ids=ids, upload_batch_id=moengage_upload_batch.id
        )
    moengage_upload_batch.update_safely(status="all_dispatched")


@task(queue='moengage_high')
def daily_update_customer_segment_data_on_moengage(days_before=1):
    """
    Daily update customer segment data on MoEngage (ME) in bulk
    for the data updated in the previous X days
    """

    # update customer who were updated on ANA in the last day(s)
    now = timezone.localtime(timezone.now())
    cutoff_datetime = now - timezone.timedelta(days=days_before)

    customer_ids = CustomerSegmentationComms.objects.filter(
        udate__gte=cutoff_datetime,
        customer_id__isnull=False,
    ).values_list('customer_id', flat=True)

    # sending
    moengage_upload_batch = MoengageUploadBatch.objects.create(
        type=MoengageEventType.CUSTOMER_SEGMENTATION,
        data_count=len(customer_ids),
    )
    for ids in chunks(customer_ids, MAX_EVENT):
        send_customer_segment_moengage_bulk.delay(
            customer_ids=ids,
            upload_batch_id=moengage_upload_batch.id
        )
    moengage_upload_batch.update_safely(status="all_dispatched")


@task(queue='moengage_high')
def bulk_process_moengage_streams(bulk_data: List):
    """
    Async process to run the bulk data sequentially to hopefully reduce racing condition.

    Args:
        bulk_data (List): A list of dictionaries from MoEngageStream's Request payload.
    """
    bulk_data = preprocess_moengage_stream(bulk_data)
    for event in bulk_data:
        try:
            trigger_moengage_streams(event)
        except MoengageCallbackError as e:
            logger.info(
                {
                    'action': 'bulk_process_moengage_streams',
                    'data': event,
                    'error': str(e),
                    'message': 'Unexpected event code.',
                }
            )
        except Exception as e:
            logger.info(
                {
                    'action': 'bulk_process_moengage_streams',
                    'data': event,
                    'error': str(e),
                    'message': 'An unknown error occurred.',
                }
            )


@task(queue='moengage_high')
def trigger_moengage_streams(event: Dict):
    """
    Identify MoEngageStream event code and redirect to processing function.

    Args:
        event (Dict): A dictionary containing a single MoEngageStream data.
    """
    event_code = event['event_code']
    if event_code in list(InAppStreamsStatus.keys()):
        parse_moengage_inapp_event.delay(event)
    elif event_code in list(EmailStatusMapping['MoEngageStream'].keys()):
        parse_moengage_email_event.delay(event)
    elif event_code in list(PnNotificationStreams.keys()):
        parse_moengage_pn_event.delay(event)
    elif event_code in list(SmsStreamsStatus.keys()):
        parse_moengage_sms_event.delay(event)
    elif event_code in list(InstallStreamsStatus.keys()):
        parse_moengage_install_event.delay(event)
    elif event_code == 'MOE_RESPONSE_SUBMITTED':
        # This event code is customized event for very specific purpose. Do not use for general purpose.
        parse_moengage_response_submitted_event.delay(event)
    else:
        if event_code in list(OnsiteMessagingStreamsStatus.keys()):
            logger.info({
                'action': 'trigger_moengage_streams',
                'message': 'OSM event detected on Streams.',
                'event': event,
            })
            raise MoengageCallbackError(f"OSM event code detected but not processed")

        raise MoengageCallbackError(f"Event code not recognized: {event_code}")


@task(queue='moengage_low')
def parse_moengage_inapp_event(event):
    stream = parse_stream_data(event, 'INAPP')
    update_inapp_notif_details(stream, is_stream=True)


@task(queue='moengage_low')
def parse_moengage_email_event(event):
    stream = parse_stream_data(event, 'EMAIL')
    update_email_details(stream, is_stream=True)


@task(queue='moengage_low')
def parse_moengage_pn_event(event):
    stream = parse_stream_data(event, 'PN')
    send_pn_details_from_moengage_streams(stream, is_stream=True)


@task(queue='moengage_low')
def parse_moengage_sms_event(event):
    stream = parse_stream_data(event, 'SMS')
    update_sms_details(stream, is_stream=True)


@task()
def parse_moengage_install_event(event):
    event_code = event['event_code']
    save_data = dict()

    try:
        if 'uid' in event:
            save_data.update({'customer_id': event['uid']})

        if 'application_id' in event['user_attributes']:
            save_data.update({'application_id': event['user_attributes']['application_id']})

        if "Campaign ID" in event['event_attributes']:
            save_data.update({'campaign_code': event["event_attributes"]["Campaign ID"]})

        if 'event_time' in event:
            time = event['event_time']
            event_time = datetime.fromtimestamp(time)
            save_data.update({'event_time': event_time})

        if 'event_code' in event:
            save_data.update({'event_code': event['event_code']})

        customer_id = save_data["customer_id"]
        application_id = save_data["application_id"]
        check_data = ('', '0', 0, None)

        if application_id in check_data and customer_id not in check_data:
            application = Application.objects.filter(customer_id=customer_id).order_by('cdate').last()
            if application:
                application_id = application.pk
                save_data.update({'application_id': application_id})

        if application_id not in check_data and customer_id in check_data:
            application = Application.objects.get_or_none(pk=application_id)
            if application:
                customer_id = application.customer_id
                save_data.update({'customer_id': customer_id})

        logger.info({
            'message': 'parse_moengage_install_event Event code {}'.format(event_code),
            'action': 'parse_moengage_install_event',
            'module': 'moengage',
            'event_code': event_code,
            'event': event,
        })

        MoengageCustomerInstallHistory.objects.create(**save_data)
        return

    except Exception as e:
        logger.exception({
            'message': 'parse_moengage_install_event Event code is not stored. {}'.format(event_code),
            'action': 'parse_moengage_install_event',
            'module': 'moengage',
            'event_code': event_code,
            'event': event,
            'error': e
        })
        return


@task(queue='moengage_low')
def parse_moengage_response_submitted_event(event: Dict):
    """
    Parses MoEngageStream data of 'MOE_RESPONSE_SUBMITTED' event to store unique users.

    Args:
        event (Dict): A dictionary containing a MoEngageStream data.
    """
    event_attributes = event['event_attributes']
    user_attributes = event['user_attributes']
    unique_event_keys = ['USER_ATTRIBUTE_USER_EMAIL', 'USER_ATTRIBUTE_USER_MOBILE']
    common_event_keys = ['USER_ATTRIBUTE_USER_FIRST_NAME']

    # We check if this user already exist based on keys in unique_key.
    save_data = {
        OnsiteMessagingStreamKeyMapping[key]: event_attributes[key]
        for key in unique_event_keys
        if key in event_attributes
    }

    moengage_user, created = MoengageOsmSubscriber.objects.get_or_create(**save_data)
    if not created:
        logger.info({
            'action': 'parse_moengage_response_submitted_event',
            'message': 'Email and phone number existed.',
            'event_attributes': event_attributes,
            'user_attributes': user_attributes,
        })
    else:
        # Update the other data into the created object.
        if 'moengage_user_id' in user_attributes.keys():
            save_data['moengage_user_id'] = user_attributes['moengage_user_id']

        for key in common_event_keys:
            if event_attributes.get(key):
                save_data[OnsiteMessagingStreamKeyMapping[key]] = event_attributes[key]
        moengage_user.update_safely(**save_data)


@task(queue='collection_cron')
def get_and_store_oldest_unpaid_account_payment():
    db_name = REPAYMENT_ASYNC_REPLICA_DB
    feature_setting = FeatureSetting.objects.filter(
        feature_name=AccountPaymentCons.ACCOUNT_PAYMENT,
        is_active=True).last()

    dpds_to_snapshot = []
    if feature_setting:
        params = feature_setting.parameters
        dpds_to_snapshot = params['dpds_to_snapshot']

    if not dpds_to_snapshot:
        return

    now = timezone.localtime(timezone.now())
    start_of_day = now.replace(hour=0, minute=0, second=0, microsecond=0)
    end_of_day = start_of_day + timedelta(days=1)
    oldest_account_payment_ids = get_oldest_unpaid_account_payment_ids(db_name=db_name)
    existing_oldest_account_payments_ids = []

    for batched_oldest_account_payment_ids in batch_pk_query_with_cursor(
        oldest_account_payment_ids, batch_size=2500):
        # this not repointing to replica, cause there's logic to update column on next line code
        existing_oldest_account_payments = OldestUnpaidAccountPayment.objects.filter(
            cdate__gte=start_of_day,
            cdate__lt=end_of_day,
            account_payment_id__in=list(batched_oldest_account_payment_ids),
        )

        existing_oldest_account_payments_ids = []
        if existing_oldest_account_payments:
            existing_oldest_account_payments.update(snapshot_ts=now)

            existing_oldest_account_payments_ids = list(
                existing_oldest_account_payments.distinct('account_payment_id').values_list(
                    'account_payment_id', flat=True
                )
            )

        oldest_unpaid_account_payments = []

        for dpd in dpds_to_snapshot:
            new_dpd = dpd * -1
            due_date_target = now + relativedelta(days=new_dpd)

            unpaid_account_payments = AccountPayment.objects.using(db_name).filter(
                due_date=due_date_target,
            ).not_paid_active().filter(
                id__in=list(batched_oldest_account_payment_ids)).exclude(
                    id__in=existing_oldest_account_payments_ids).extra(
                    select={'dpd': dpd}).values('id', 'due_amount', 'dpd')

            unpaid_account_payments = list(unpaid_account_payments)

            oldest_unpaid_account_payments += unpaid_account_payments

        bulk_create_data = []

        for item in oldest_unpaid_account_payments:
            account_payment_id = item.get('id')
            dpd = item.get('dpd')
            due_amount = item.get('due_amount')

            data = OldestUnpaidAccountPayment(
                account_payment_id=account_payment_id,
                dpd=dpd,
                due_amount=due_amount
            )
            bulk_create_data.append(data)

        OldestUnpaidAccountPayment.objects.bulk_create(bulk_create_data)


# one time run for ENH 1203
@task(queue='moengage_low')
def retroload_template_postfix_data():
    retroload_template_postfix_email_history.delay()
    retroload_template_postfix_sms_history.delay()
    retroload_template_postfix_inapp_notification.delay()
    # NOTE: PNBlast can't retroload as template name can't duplicate there.


@task(queue='moengage_low')
def retroload_template_postfix_email_history():
    email_history_obj = EmailHistory.objects.filter(source='MOENGAGE',template_code__contains="@")
    for email_history in email_history_obj.iterator():
        email_history.template_code = search_and_remove_postfix_data(email_history.template_code, "@")
        email_history.save()


@task(queue='moengage_low')
def retroload_template_postfix_sms_history():
    sms_history_obj = SmsHistory.objects.filter(source='MOENGAGE', template_code__contains="@")
    for sms_history in sms_history_obj.iterator():
        sms_history.template_code = search_and_remove_postfix_data(sms_history.template_code, "@")
        sms_history.save()


@task(queue='moengage_low')
def retroload_template_postfix_inapp_notification():
    inapp_history_obj =  InAppNotificationHistory.objects.filter(source='MOENGAGE', template_code__contains="@")
    for history in inapp_history_obj.iterator():
        history.template_code = search_and_remove_postfix_data(history.template_code, "@")
        history.save()


@task(queue='moengage_high')
def update_moengage_for_payment_received_task(account_trx_id):
    account_trx = AccountTransaction.objects.get_or_none(pk=account_trx_id)
    if account_trx:
        update_moengage_for_payment_received(account_trx)


@task(queue='collection_normal')
@validate_activate_experiment(ExperimentConst.COLLECTION_TAILOR_EXPERIMENT)
def trigger_send_user_attribute_collection_tailor_experiment(*args, **kwargs):
    redis_client = get_redis_client()
    experiment_data = redis_client.get(RedisKey.TAILOR_EXPERIMENT_DATA)
    if not experiment_data:
        return
    experiment_data = literal_eval(experiment_data)
    if not experiment_data:
        return

    moengage_upload_batch = MoengageUploadBatch.objects.create(
        type=MoengageEventType.ATTRIBUTE_FOR_COLLECTION_TAILOR,
        data_count=len(experiment_data))

    send_user_attributes_to_moengage_for_tailor_exp.delay(moengage_upload_batch.id)
    moengage_upload_batch.update_safely(status="all_dispatched")


@task(queue='collection_normal')
def send_event_autodebit_failed_deduction_task(account_payment_id, customer_id, vendor):
    customer = Customer.objects.get_or_none(pk=customer_id)
    if not customer:
        return
    send_event_autodebit_failed_deduction(account_payment_id, customer, vendor)


@task(queue='collection_normal')
@validate_activate_experiment(ExperimentConst.LATE_FEE_EARLIER_EXPERIMENT)
def trigger_send_user_attribute_late_fee_earlier_experiment(*args, **kwargs):
    fn_name = 'trigger_send_user_attribute_late_fee_earlier_experiment'
    logger.info({
        'task_name': fn_name,
        'state': 'start'
    })
    late_fee_earlier_experiment = kwargs['experiment']
    experiment_data = ExperimentGroup.objects.filter(
        experiment_setting=late_fee_earlier_experiment).count()
    if not experiment_data:
        return

    moengage_upload_batch = MoengageUploadBatch.objects.create(
        type=MoengageEventType.USERS_ATTRIBUTE_FOR_LATE_FEE_EXPERIMENT,
        data_count=experiment_data)

    send_user_attributes_to_moengage_for_late_fee_earlier_exp.delay(moengage_upload_batch.id)
    moengage_upload_batch.update_safely(status="all_dispatched")


@task(queue='collection_normal')
def send_user_attribute_late_fee_experiment_changed_is_active():
    # this tasks only running if we have some changes on ExperimentSetting django admin
    # and only change is_active, because we need to send the data become control if
    # experiment off
    fn_name = 'send_user_attribute_late_fee_experiment_changed_is_active'
    logger.info({
        'task_name': fn_name,
        'state': 'start'
    })
    experiment_data = ExperimentGroup.objects.filter(
        experiment_setting__code=ExperimentConst.LATE_FEE_EARLIER_EXPERIMENT).count()
    if not experiment_data:
        return

    moengage_upload_batch = MoengageUploadBatch.objects.create(
        type=MoengageEventType.USERS_ATTRIBUTE_FOR_LATE_FEE_EXPERIMENT,
        data_count=experiment_data)

    send_user_attributes_to_moengage_for_late_fee_earlier_exp.delay(moengage_upload_batch.id)
    moengage_upload_batch.update_safely(status="all_dispatched")


@task(queue='repayment_high')
def send_pn_activated_autodebet(customer_id, payday, vendor, next_due):
    customer = Customer.objects.get_or_none(pk=customer_id)
    if customer:
        send_event_activated_autodebet(
            customer, MoengageEventType.ACTIVATED_AUTODEBET, payday, vendor, next_due
        )


@task(queue='repayment_normal')
def send_event_autodebet_bri_expiration_handler_task(account_payment_id, customer_id):
    customer = Customer.objects.get_or_none(pk=customer_id)
    if not customer:
        return
    send_event_autodebet_bri_expiration_handler(account_payment_id, customer)


@task(queue='repayment_normal')
def send_pn_activated_oneklik(customer_id, cdate):
    customer = Customer.objects.get_or_none(pk=customer_id)
    if customer:
        send_event_activated_oneklik(customer, MoengageEventType.ACTIVATED_ONEKLIK, cdate)


@task(queue='moengage_high')
def trigger_update_risk_segment_customer_attribute_for_moengage():
    pcmr = (
        PdCollectionModelResult.objects.extra(
            where=[
                "range_from_due_date ~ '^[-]?[0-9]+$'",  # cast range_from_due_date as integer
                "CAST(range_from_due_date AS INTEGER) < 0",
            ]
        )
        .filter(
            prediction_date=timezone.localtime(timezone.now()).date(),
            account_payment__isnull=False,
        )
        .annotate(customer_id=F('account__customer'))
        .order_by('customer_id', '-id')
        .distinct('customer_id')
        .values('customer_id', 'sort_method')
    )

    valid_customers = [
        {
            "customer_id": entry["customer_id"],
            "risk_segment": entry["sort_method"].split("_", 2)[-1],
        }
        for entry in pcmr
        if entry["sort_method"].startswith("sort_02_")
    ]

    if not valid_customers:
        return

    moengage_upload_batch = MoengageUploadBatch.objects.create(
        type=MoengageEventType.RISK_SEGMENT_ATTRIBUTE_UPDATE, data_count=len(valid_customers)
    )

    logger.info(
        {
            "action": "trigger_update_risk_segment_customer_attribute_for_moengage",
            "moengage_upload_batch_id": moengage_upload_batch.id,
            "data_count": moengage_upload_batch.data_count,
        }
    )

    for customers in chunks(valid_customers, MAX_EVENT):
        send_customer_risk_segment_bulk.delay(customers, moengage_upload_batch.id)
    moengage_upload_batch.update_safely(status="all_dispatched")
