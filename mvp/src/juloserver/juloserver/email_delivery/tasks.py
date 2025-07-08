from __future__ import absolute_import

from builtins import str
import logging
from typing import Dict

from celery import task
from django.utils import timezone

from juloserver.comms.services.email_service import (
    get_email_vendor,
    send_email,
)
from juloserver.email_delivery.constants import EmailStatusMapping
from juloserver.julo.clients import (
    get_julo_email_client,
    get_julo_sentry_client,
)
from juloserver.julo.clients import get_julo_nemesys_client
from juloserver.julo.constants import (
    FeatureNameConst,
    ReminderTypeConst,
)
from juloserver.julo.exceptions import EmailNotSent
from juloserver.julo.exceptions import JuloException
from juloserver.julo.models import (EmailHistory,
                                    FeatureSetting,
                                    Payment)
from juloserver.julo.product_lines import ProductLineCodes
from juloserver.julo.services2.reminders import Reminder
from juloserver.julo.services import get_payment_due_date_by_delta, get_oldest_payment_due
from juloserver.email_delivery.services import (
    email_history_kwargs_for_account_payment,
    email_history_kwargs_for_payment,
    get_payment_info_for_email_reminder,
)
from juloserver.email_delivery.services import get_all_payments_for_reminder
from juloserver.email_delivery.services import create_email_history_for_payment
from juloserver.email_delivery.services import (
    get_payment_info_for_email_reminder_for_unsent_moengage)
from juloserver.moengage.constants import UNSENT_MOENGAGE
from juloserver.streamlined_communication.models import StreamlinedCommunication
from juloserver.julo.services import check_payment_is_blocked_comms
from juloserver.account_payment.models import AccountPayment
from juloserver.streamlined_communication.services import (
    is_ptp_payment_already_paid,
)
from django.template.loader import render_to_string
from juloserver.julo.statuses import PaymentStatusCodes
from juloserver.streamlined_communication.services import (
    filter_streamlined_based_on_partner_selection)
from juloserver.monitors.notifications import send_slack_bot_message

from juloserver.julo.constants import WorkflowConst
from juloserver.streamlined_communication.constant import (
    CommunicationPlatform,
    Product,
)
from juloserver.minisquad.constants import REPAYMENT_ASYNC_REPLICA_DB
from datetime import timedelta
from juloserver.omnichannel.services.utils import (
    get_omnichannel_comms_block_active,
    is_account_payment_owned_by_omnichannel_customer,
)
from juloserver.omnichannel.services.settings import OmnichannelIntegrationSetting
from juloserver.streamlined_communication.tasks import evaluate_email_reachability

logger = logging.getLogger(__name__)


# Public interface #############################################################


@task(queue='moengage_high')
def send_email_and_track_history(
        email_history_id,
        subject,
        content,
        email_to,
        email_from,
        template_code=None,
        **kwargs):
    """
    Deprecated. Please use send_email() instead.
       from juloserver.comms.services.email_service import send_email
       send_email(template_code, to_email, content, from_email)
    """
    sent_email_and_track_feature_setting = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.SENT_EMAIl_AND_TRACKING,
        is_active=True, ).last()
    if not sent_email_and_track_feature_setting:
        return

    email_history = EmailHistory.objects.get_or_none(id=email_history_id)
    if not email_history:
        JuloException("email_history_id: %s not found" % email_history_id)

    julo_email_client = get_julo_email_client()
    try:
        response_status, body, headers = julo_email_client.send_email(
            subject, content, email_to,
            email_from, **kwargs)
        if response_status == 202:
            status = 'sent_to_sendgrid'
            error_message = None
        else:
            status = 'error'
            error_message = body
        sg_message_id = headers['X-Message-Id']
    except EmailNotSent as e:
        status = 'error'
        error_message = str(e)
        sg_message_id = None
    try:
        pre_header = kwargs['pre_header']
    except KeyError:
        pre_header = None
    email_history.update_safely(
        status=status,
        error_message=error_message,
        sg_message_id=sg_message_id,
        subject=subject,
        message_content=content,
        template_code=template_code,
        to_email=email_to,
        pre_header=pre_header)


# Callback tasks ###############################################################


@task(queue="comms")
def update_email_history_status(item: Dict):
    """
    Updates email history status based on data from SendGrid.

    Args:
        item (Dict): A dictionary of data sent from SendGrid.
    """
    logger.info({
        'sg_message_id': item['sg_message_id'],
        'email_status': item['event'],
    })

    sg_message_id = item['sg_message_id'][:22]
    status = str(item['event']).lower()
    if status not in list(EmailStatusMapping['SendGrid'].keys()):
        logger.info({
            'action': 'update_email_history_status',
            'sg_message_id': item['sg_message_id'],
            'event': status,
            'message': 'Unexpected status detected.'
        })
    # Identify if a bounce is hard bounce or soft bounce.
    if status == 'bounce':
        bounce_type = item['type'].lower()
        if bounce_type == 'bounce':
            status = 'hard_bounce'
        elif bounce_type == 'blocked':
            status = 'soft_bounce'
        else:
            status = 'unknown_bounce'
            logger.info({
                'action': 'update_email_history_status',
                'sg_message_id': item['sg_message_id'],
                'event': status,
                'type': bounce_type,
                'message': 'Unexpected bounce type detected.'
            })

        logger.info({
            'action': 'update_email_history_status',
            'sg_message_id': item['sg_message_id'],
            'event': status,
            'type': bounce_type,
            'reason': item.get('reason', ''),
            'message': 'Logging SendGrid bounce reason.'
        })
    else:
        status = EmailStatusMapping['SendGrid'].get(status, 'unknown')

    if 'category' in item and 'nemesys' in item['category']:
        logger.info({
            'action': 'hit_nemesys_api',
            'sg_message_id': item['sg_message_id'],
            'category': item['category'],
            'status': status
        })
        nemesys_client = get_julo_nemesys_client()
        nemesys_client.update_email_delivery_status([item])
        return

    email_history = EmailHistory.objects.get_or_none(sg_message_id=sg_message_id)
    if email_history is None:
        logger.error({
            'sg_message_id': sg_message_id,
            'status': 'message_id_not_found'
        })
        return

    logger.info({
        'sg_message_id': sg_message_id,
        'email_status': status,
        'status': 'checking_message_id'
    })

    # Rejects updating regressing email status. E.g. Opened email should not return to processed.
    if email_history.status in ('delivered', 'clicked', 'open') and status == 'processed':
        logger.info({
            'action': 'update_email_history_status',
            'message': 'cannot update email history status',
            'sg_message_id': sg_message_id,
            'current_email_status': email_history.status,
            'new_email_status': status,
        })
        return

    email_history.update_safely(status=status)
    evaluate_email_reachability.delay(
        email_history.to_email, email_history.customer_id, status, sg_message_id, item['timestamp']
    )

    # Process SendGrid callback event for comms service.
    try:
        from juloserver.comms.services.email_service import process_sendgrid_callback_event

        process_sendgrid_callback_event(item)
    except Exception as e:
        logger.error(
            {
                'action': 'update_email_history_status',
                'sg_message_id': item['sg_message_id'],
                'event': item['event'],
                'error': str(e),
                'message': 'Error processing SendGrid callback event for comms service.',
            }
        )
        get_julo_sentry_client().captureException()
    # end: Process SendGrid callback event for comms service.

    # Retry mechanism for bounced emails
    payment_reminder_sendgrid_bounce_list_takeout_feature_setting = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.EMAIL_PAYMENT_REMINDER_SENDGRID_BOUNCE_TAKEOUT, is_active=True
    ).last()
    if payment_reminder_sendgrid_bounce_list_takeout_feature_setting:
        retry_bounce_email(email_history)


def retry_bounce_email(email_history: EmailHistory) -> bool:
    """
    Attempt to send second email for bounced email from SendGrid.

    Args:
        email_history (EmailHistory): EmailHistory object based on callback.

    Returns:
        (bool): True if retry is done.
            False if not doing retry.
    """
    is_retry = False

    if email_history.status in ('soft_bounce', 'hard_bounce'):
        streamlined_payment_reminder_template_codes = StreamlinedCommunication.objects.filter(
            communication_platform=CommunicationPlatform.EMAIL,
            time_sent__isnull=False,
            is_automated=True,
            extra_conditions=UNSENT_MOENGAGE,
            dpd__isnull=False
        ).values_list('template_code', flat=True)

        if email_history.template_code in streamlined_payment_reminder_template_codes:
            today = timezone.localtime(timezone.now())
            today_start_of_day = today.replace(hour=0, minute=0, second=0, microsecond=0)
            tomorrow_start_of_day = today_start_of_day + timedelta(days=1)

            total_duplicate_email = EmailHistory.objects.using(REPAYMENT_ASYNC_REPLICA_DB).filter(
                cdate__gte=today_start_of_day,
                cdate__lt=tomorrow_start_of_day,
                to_email=email_history.to_email,
                template_code=email_history.template_code
            ).count()

            if total_duplicate_email < 2:
                account_payment = AccountPayment.objects.filter(
                    id=email_history.account_payment_id,
                ).exclude(
                    status__in=(PaymentStatusCodes.PAID_ON_TIME,
                                PaymentStatusCodes.PAID_WITHIN_GRACE_PERIOD,
                                PaymentStatusCodes.PAID_LATE)
                ).last()
                streamlined_comm = StreamlinedCommunication.objects.get_or_none(
                    template_code=email_history.template_code
                )

                logger.info({
                    'action': 'retry_bounce_email',
                    'message': 'Attempt resend bounced email.',
                    'account_payment_id': account_payment.id,
                    'streamlined_communication_id': streamlined_comm.id
                })

                if account_payment and streamlined_comm:
                    email_client = get_julo_email_client()
                    email_client.delete_email_from_bounce(email_history.to_email)
                    send_email_payment_reminder_for_unsent_moengage.delay(
                        account_payment.id, streamlined_comm.id, 'retry_bounce_email')
                    is_retry = True

    return is_retry


# Reminder tasks ###############################################################
@task(queue='collection_low')
def send_email_payment_reminder(payment_id, streamlined_comm_id):
    payment = Payment.objects.select_related("loan__application").get(pk=payment_id)
    streamlined = StreamlinedCommunication.objects.get_or_none(pk=streamlined_comm_id)
    oldest_payment = get_oldest_payment_due(payment.loan)
    if not oldest_payment or oldest_payment.id != payment.id:
        return

    application = payment.loan.application
    if application.partner and application.partner.is_grab:
        return

    email_content, email_to, email_from = get_payment_info_for_email_reminder(payment, streamlined)
    email_history_kwargs = email_history_kwargs_for_payment(payment_id)
    if streamlined.ptp is not None:
        email_history_kwargs['category'] = "PTP"

    reminder = Reminder()
    reminder.create_reminder_history(
        payment,
        email_history_kwargs.get('customer_id'),
        streamlined.template_code,
        get_email_vendor(),
        ReminderTypeConst.EMAIL_TYPE_REMINDER,
    )
    is_success, comm_request_id = send_email(
        template_code=streamlined.template_code,
        to_email=email_to,
        content=email_content,
        from_email=email_from,
        customer_id=email_history_kwargs.get('customer_id'),
        email_history_kwargs=email_history_kwargs,
    )
    return is_success, comm_request_id, payment_id, streamlined_comm_id


@task(queue='collection_low')
def trigger_all_email_payment_reminders(streamlined_comm_id):
    today = timezone.localtime(timezone.now()).date()
    query = get_all_payments_for_reminder(today)
    streamlined = StreamlinedCommunication.objects.get_or_none(pk=streamlined_comm_id)
    if not streamlined:
        return

    if not streamlined.is_automated:
        logger.info({
            'status': 'dismiss',
            'action': 'trigger_all_email_payment_reminders',
            'streamlined_comm_id': streamlined_comm_id
        })
        return

    # for handle PTP since PTP have more than one product
    if streamlined.product != 'internal_product':
        product_lines = getattr(ProductLineCodes, streamlined.product)()
    else:
        product_lines = ProductLineCodes.mtl() + ProductLineCodes.stl()

    query = query.filter(loan__application__product_line__product_line_code__in=product_lines)
    payments = None
    if streamlined.dpd is not None:
        due_date = get_payment_due_date_by_delta(streamlined.dpd)
        payments = query.filter(ptp_date__isnull=True, due_date=due_date)

    ptp_date = None
    if streamlined.ptp is not None:
        ptp_date = get_payment_due_date_by_delta(int(streamlined.ptp))
        payments = query.filter(
            ptp_date__isnull=False,
            ptp_date=ptp_date
        )

    for payment in payments:
        if check_payment_is_blocked_comms(payment, 'email'):
            continue
        if ptp_date is not None:
            is_ptp_paid = is_ptp_payment_already_paid(payment.id, ptp_date)
            if is_ptp_paid:
                logger.info({
                    'status': 'send_automated_comm_sms',
                    'payment_id': payment.id,
                    'message': "ptp already paid",
                    'ptp_date': ptp_date
                })
                continue
        send_email_payment_reminder.delay(payment.id, streamlined_comm_id)
    sl_msg = "*Template: {}* - trigger_all_email_payment_reminders (streamlined_id - {})". \
        format(str(streamlined.template_code), str(streamlined.id))
    send_slack_bot_message('alerts-comms-prod-email', sl_msg)


@task(queue='collection_low')
def send_email_payment_reminder_for_unsent_moengage(
    account_payment_id, streamlined_comm_id, logger_origin
):

    # omnichannel customer exclusion
    omnichannel_exclusion_request = get_omnichannel_comms_block_active(
        OmnichannelIntegrationSetting.CommsType.EMAIL
    )

    account_payment = AccountPayment.objects.get(pk=account_payment_id)

    if (
        omnichannel_exclusion_request.is_excluded
        and is_account_payment_owned_by_omnichannel_customer(
            exclusion_req=omnichannel_exclusion_request,
            account_payment=account_payment,
        )
    ):
        return

    streamlined = StreamlinedCommunication.objects.get_or_none(pk=streamlined_comm_id)
    logger.info({
        'action': 'send_email_payment_reminder_for_unsent_moengage',
        'streamlined_comm': streamlined.template_code,
        'account_payment_id': account_payment_id,
        'message': "triggered from {}".format(logger_origin)
    })

    email_content, to_email, from_email = get_payment_info_for_email_reminder_for_unsent_moengage(
        account_payment, streamlined
    )
    email_history_kwargs = email_history_kwargs_for_account_payment(account_payment_id)
    reminder = Reminder()
    reminder.create_j1_reminder_history(
        account_payment,
        email_history_kwargs.get('customer_id'),
        streamlined.template_code,
        get_email_vendor(),
        ReminderTypeConst.EMAIL_TYPE_REMINDER,
    )
    is_success, comm_request_id = send_email(
        template_code=streamlined.template_code,
        to_email=to_email,
        content=email_content,
        from_email=from_email,
        customer_id=email_history_kwargs.get('customer_id'),
        email_history_kwargs=email_history_kwargs,
    )
    return is_success, comm_request_id, account_payment_id, streamlined_comm_id


@task(queue='collection_low')
def send_email_ptp_payment_reminder_j1(account_payment, streamlined):
    """
    Trigger send email and track history for J1 and JTurbo products.

    Args:
        account_payment (AccountPayment): AccountPayment model obj
        streamlined (StreamlinedCommunication): StreamlinedCommunication model obj
    """
    # omnichannel customer exclusion
    omnichannel_exclusion_request = get_omnichannel_comms_block_active(
        OmnichannelIntegrationSetting.CommsType.EMAIL
    )

    if (
        omnichannel_exclusion_request.is_excluded
        and is_account_payment_owned_by_omnichannel_customer(
            exclusion_req=omnichannel_exclusion_request,
            account_payment=account_payment,
        )
    ):
        return

    email_content, email_to, email_from = get_payment_info_for_email_reminder(
        account_payment, streamlined
    )
    email_history_kwargs = email_history_kwargs_for_account_payment(account_payment.id)
    if streamlined.ptp is not None:
        email_history_kwargs['category'] = "PTP"

    reminder = Reminder()
    reminder.create_j1_reminder_history(
        account_payment,
        email_history_kwargs.get('customer_id'),
        streamlined.template_code,
        get_email_vendor(),
        ReminderTypeConst.EMAIL_TYPE_REMINDER,
    )

    is_success, comm_request_id = send_email(
        template_code=streamlined.template_code,
        to_email=email_to,
        content=email_content,
        from_email=email_from,
        customer_id=email_history_kwargs.get('customer_id'),
        email_history_kwargs=email_history_kwargs,
    )
    return is_success, comm_request_id, account_payment.id, streamlined.id


@task(queue='collection_low')
def trigger_all_ptp_email_payment_reminders_j1(streamlined_communication):
    """Process the account payments for J1 and JTurbo products.

    Args:
        streamlined_communication (StreamlinedCommunication): StreamlinedCommunication model obj
    """
    streamlined_communication.refresh_from_db()
    if not streamlined_communication:
        return

    if not streamlined_communication.is_automated:
        logger.info({
            'status': 'dismiss',
            'action': 'trigger_all_ptp_email_payment_reminders_j1',
            'streamlined_comm_id': streamlined_communication.id
        })
        return

    # Only handles PTP email notification
    if streamlined_communication.ptp is None:
        return

    account_payments = []
    product_lines = getattr(ProductLineCodes, streamlined_communication.product)()
    query = AccountPayment.objects.not_paid_active() \
        .filter(account__application__product_line__product_line_code__in=product_lines)
    if streamlined_communication.product.lower() == Product.EMAIL.JTURBO:
        query = query.filter(account__account_lookup__workflow__name=WorkflowConst.JULO_STARTER,)
    elif streamlined_communication.product.lower() == Product.EMAIL.J1:
        query = query.filter(account__account_lookup__workflow__name=WorkflowConst.JULO_ONE,)

    ptp_date = get_payment_due_date_by_delta(int(streamlined_communication.ptp))
    account_payments = query.filter(
        ptp_date__isnull=False,
        ptp_date=ptp_date
    )

    account_payments = filter_streamlined_based_on_partner_selection(streamlined_communication,
                                                                     account_payments)
    for account_payment in account_payments:

        if ptp_date is not None:
            is_ptp_paid = is_ptp_payment_already_paid(account_payment.id,
                                                      ptp_date,
                                                      is_account_payment=True)
            if is_ptp_paid:
                logger.info({
                    'status': 'trigger_all_ptp_email_payment_reminders_j1',
                    'payment_id': account_payment.id,
                    'message': "ptp already paid",
                    'ptp_date': ptp_date
                })
                continue
        send_email_ptp_payment_reminder_j1.delay(account_payment, streamlined_communication)
    sl_msg = "*Template: {}* - trigger_all_ptp_email_payment_reminders_j1 (streamlined_id - {})". \
        format(str(streamlined_communication.template_code), str(streamlined_communication.id))
    send_slack_bot_message('alerts-comms-prod-email', sl_msg)


@task(queue='collection_low')
def send_email_is_5_days_unreachable(payment_id, is_account_payment):
    if is_account_payment:
        payment_or_account_payment = AccountPayment.objects. \
            filter(id=payment_id, status_id__lt=PaymentStatusCodes.PAID_ON_TIME).last()
        if not payment_or_account_payment:
            return

        application = payment_or_account_payment.account.application_set.last()
    else:
        payment_or_account_payment = Payment.objects. \
            filter(id=payment_id, payment_status_id__lt=PaymentStatusCodes.PAID_ON_TIME).last()
        if not payment_or_account_payment:
            return

        application = payment_or_account_payment.loan.application

    fullname = application.full_name_only
    title = application.gender_title
    today = timezone.localtime(timezone.now()).date()
    context = {
        'fullname': fullname,
        'title': title,
        'year': today.strftime('%Y'),
    }
    template_code = "call_not_answered_email"
    message = render_to_string(template_code + '.html', context)

    subject = 'Informasi Penting Untuk Akun Anda'
    email_to = application.email if application.email else application.customer.email
    email_from = "collections@julo.co.id"
    content_type = "text/html"

    email_history = create_email_history_for_payment(payment_or_account_payment.id,
                                                     is_account_payment)
    email_history.category = "5 days unreached"
    email_history.save()

    send_email_and_track_history.delay(
        email_history.id, subject, message, email_to=email_to, template_code=template_code,
        email_from=email_from, content_type=content_type)
