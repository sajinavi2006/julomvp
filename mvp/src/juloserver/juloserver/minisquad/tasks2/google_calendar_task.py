import os
import logging

from celery import task
from django.utils import timezone

from datetime import timedelta

from juloserver.account_payment.models import AccountPayment
from juloserver.julo.models import PTP
from juloserver.minisquad.constants import GoogleCalendar
from juloserver.minisquad.models import (
    CollectionCalendarsParameter,
)
from juloserver.minisquad.services2.google_calendar_related import (
    mapping_data_google_calendar_single,
    check_google_calendar_invitation,
    mapping_data_google_calendar_event,
    get_google_calendar_service,
)
from juloserver.minisquad.services import get_oldest_unpaid_account_payment_ids
from juloserver.julo.product_lines import ProductLineCodes
from juloserver.julo.clients import get_julo_sentry_client

from juloserver.moengage.utils import chunks

logger = logging.getLogger(__name__)


@task(queue='collection_normal')
def set_google_calendar_when_paid(**kwargs):
    fn_name = 'set_google_calendar_when_paid'
    logger.info({
        'action': fn_name,
        'message': 'task begin'
    })
    google_calendar_invitation = check_google_calendar_invitation()
    if not google_calendar_invitation:
        logger.warning({
            'action': fn_name,
            'message': 'google calendar feature setting inactive'
        })
        return

    retries = set_google_calendar_when_paid.request.retries
    paid_off_account_payment_id = kwargs.get('paid_off_account_payment_id')
    timeout = kwargs.get('timeout', 120)
    today = timezone.localtime(timezone.now())
    tomorrow = today + timedelta(days=1)
    if google_calendar_invitation.parameters:
        timeout = google_calendar_invitation.parameters.get('timeout', 120)

    try:
        paid_off_account_ids = (
            AccountPayment.objects.select_related('account')
            .filter(
                id=paid_off_account_payment_id,
                account__application__partner__id__isnull=True,
                account__application__product_line_id__in=ProductLineCodes.j1(),
            )
            .values_list('account_id', flat=True)
        )

        if not paid_off_account_ids:
            logger.warning({'action': fn_name, 'message': "there's no account payment"})
            return

        oldest_account_payments = AccountPayment.objects.filter(
            account_id__in=paid_off_account_ids, due_date__lte=today, due_amount__gt=0
        )

        if not oldest_account_payments:
            logger.warning(
                {
                    'action': fn_name,
                    'message': "there's no account payment with due date <= today",
                }
            )
            return

        for oldest_account_payment in oldest_account_payments:
            account_ids = (
                AccountPayment.objects.select_related('account')
                .filter(
                    due_date=tomorrow,
                    account_id=oldest_account_payment.account.id,
                    due_amount__gt=0,
                    account__application__partner__id__isnull=True,
                )
                .values_list('account_id', flat=True)
            )

            if not account_ids:
                logger.warning(
                    {
                        'action': fn_name,
                        'message': "there's no account payment with due date tomorrow",
                    }
                )
                return

            oldest_accounts = AccountPayment.objects.filter(
                account_id__in=account_ids, due_date__lte=today, due_amount__gt=0
            )

            if not oldest_accounts:
                logger.warning({'action': fn_name, 'message': "there's no oldest account payment"})
                return

            if google_calendar_invitation.parameters[
                GoogleCalendar.SEND_GOOGLE_CALENDAR_SINGLE_METHOD
            ]:
                for oldest_account in oldest_accounts:
                    create_google_calendar_event_with_single_method.delay(
                        account_payment_id=oldest_account.id,
                        action_log=fn_name,
                        dpd=1,
                        timeout=google_calendar_invitation.parameters.get('timeout', 120),
                    )
                logger.info({'action': fn_name, 'message': 'sent to async task'})
                return

            parameter = CollectionCalendarsParameter.objects.filter(
                is_active=True, is_single_parameter=False, is_ptp_parameter=False
            ).last()

            if not parameter:
                logger.warning({'action': fn_name, 'message': 'calendar parameter not found'})
                return

            create_google_calendar_event.delay(
                account_payment_ids=list(oldest_accounts.values_list('id', flat=True)),
                calendar_parameter_id=parameter.id,
                action_log=fn_name,
                dpd=1,
                timeout=google_calendar_invitation.parameters.get('timeout', 120),
            )
            logger.info({'action': fn_name, 'message': 'sent to async task'})

    except Exception as error:
        logger.error({
            'action': fn_name,
            'message': str(error)
        })
        if retries >= set_google_calendar_when_paid.max_retries:
            get_julo_sentry_client().captureException()
            return

        raise set_google_calendar_when_paid.retry(
            countdown=300, exc=error, max_retries=3,
            kwargs={
                'paid_off_account_payment_id': paid_off_account_payment_id,
                'timeout': timeout + (20 * retries)
            }
        )


@task(queue='collection_normal')
def google_calendar_payment_reminder():
    fn_name = 'google_calendar_payment_reminder'
    logger.info({
        'action': fn_name,
        'message': 'task begin'
    })
    google_calendar_invitation = check_google_calendar_invitation()

    if not google_calendar_invitation:
        logger.warning({
            'action': fn_name,
            'message': 'google calendar feature setting inactive'
        })
        return

    google_calendar_parameter = google_calendar_invitation.parameters \
        if google_calendar_invitation.parameters else dict()

    today = timezone.localtime(timezone.now())
    dpd = today + timedelta(days=google_calendar_parameter.get('dpd_minus'))

    oldest_account_payment_ids = list(get_oldest_unpaid_account_payment_ids())

    account_payment_ids = (
        AccountPayment.objects.select_related('account')
        .not_paid_active()
        .filter(
            due_date=dpd,
            id__in=oldest_account_payment_ids,
            account__application__partner_id__isnull=True,
            account__application__product_line_id__in=ProductLineCodes.julo_product(),
        )
        .extra(
            where=[
                """NOT EXISTS(SELECT 1 FROM "collection_calendars_reminder" ccr
        WHERE "ccr"."account_payment_id" = "account_payment"."account_payment_id"
        AND "ccr"."is_paid" = false
        AND "ccr"."collection_calendars_event_id" IS NOT NULL)"""
            ]
        )
        .distinct('id')
        .values_list('id', flat=True)
    )

    if not account_payment_ids:
        logger.warning({
            'action': fn_name,
            'message': "there's no account payment data"
        })
        return

    # mapping data for google calendar event
    action_log = 'google_calendar_payment_reminder_response'

    max_participants = google_calendar_parameter.get('max_participants')
    max_participants = max_participants if max_participants else GoogleCalendar.MAX_PARTICIPANTS

    for account_payment_ids in chunks(account_payment_ids, max_participants):
        if google_calendar_invitation.parameters[GoogleCalendar.SEND_GOOGLE_CALENDAR_SINGLE_METHOD]:
            for account_payment_id in account_payment_ids:
                create_google_calendar_event_with_single_method.delay(
                    account_payment_id=account_payment_id,
                    action_log=action_log,
                    dpd=google_calendar_parameter.get('dpd_minus'),
                    timeout=google_calendar_invitation.parameters.get('timeout', 120),
                )
            logger.info({'action': fn_name, 'message': 'sent to async task'})
            return

        parameter = CollectionCalendarsParameter.objects.filter(
            is_active=True, is_single_parameter=False, is_ptp_parameter=False
        ).last()

        if not parameter:
            logger.warning({'action': fn_name, 'message': 'calendar parameter not found'})
            return

        create_google_calendar_event.delay(
            account_payment_ids=list(account_payment_ids),
            calendar_parameter_id=parameter.id,
            action_log=action_log,
            dpd=google_calendar_parameter.get('dpd_minus'),
            timeout=google_calendar_invitation.parameters.get('timeout', 120),
        )
        logger.info({'action': fn_name, 'message': 'sent to async task'})


@task(queue='collection_normal')
def set_google_calendar_payment_reminder_by_account_payment_id(**kwargs):
    account_payment_id = kwargs.get('account_payment_id', None)
    timeout = kwargs.get('timeout', 120)
    fn_name = 'set_google_calendar_payment_reminder_by_account_payment_id'
    retries = set_google_calendar_payment_reminder_by_account_payment_id.request.retries
    try:
        logger.info({
            'action': fn_name,
            'account_payment_id': account_payment_id,
            'message': 'task begin'
        })

        if not account_payment_id:
            logger.warning({
                'action': 'set_google_calendar_payment_reminder_by_account_payment_id_skipped',
            })
            return

        ptp = PTP.objects.filter(
            account_payment=account_payment_id,
            account__application__product_line_id__in=ProductLineCodes.julo_product()
        ).last()
        if not ptp:
            logger.warning({
                'action': fn_name,
                'account_payment_id': account_payment_id,
                'message': "there's no account payment data"
            })
            return

        google_calendar_invitation = check_google_calendar_invitation()
        if not google_calendar_invitation:
            logger.warning({
                'action': fn_name,
                'account_payment_id': account_payment_id,
                'message': 'google calendar feature setting inactive'
            })
            return

        today = timezone.localtime(timezone.now()).date()
        dpd_setting = (ptp.ptp_date - today).days

        if dpd_setting < 0:
            logger.warning({
                'action': fn_name,
                'account_payment_id': account_payment_id,
                'message': 'account payment is dpd plus'
            })
            return

        # mapping data for google calendar event
        action_log = 'set_google_calendar_payment_reminder_by_account_payment_id'

        if google_calendar_invitation.parameters[GoogleCalendar.SEND_GOOGLE_CALENDAR_SINGLE_METHOD]:
            create_google_calendar_event_with_single_method.delay(
                account_payment_id=account_payment_id,
                action_log=action_log,
                dpd=dpd_setting,
                timeout=google_calendar_invitation.parameters.get('timeout', 120),
                is_ptp=True
            )
            logger.info({
                'action': fn_name,
                'message': 'sent to async task'
            })
            return

        parameter = CollectionCalendarsParameter.objects.filter(
            is_active=True, is_single_parameter=False, is_ptp_parameter=True).last()

        if not parameter:
            return

        create_google_calendar_event.delay(
            account_payment_ids=[account_payment_id],
            calendar_parameter_id=parameter.id,
            action_log=action_log,
            dpd=dpd_setting,
            timeout=google_calendar_invitation.parameters.get('timeout', 120),
            is_ptp=True
        )

        logger.info({
            'action': fn_name,
            'message': 'sent to async task'
        })
    except Exception as error:
        logger.error({
            'action': fn_name,
            'timeout': timeout,
            'account_payment_id': account_payment_id,
            'message': str(error)
        })
        if retries >= set_google_calendar_payment_reminder_by_account_payment_id.max_retries:
            get_julo_sentry_client().captureException()
            return

        raise set_google_calendar_payment_reminder_by_account_payment_id.retry(
            countdown=300, exc=error, max_retries=3,
            kwargs={
                'account_payment_id': account_payment_id,
                # add 20 sec each retries
                'timeout': timeout + (20 * retries),
            }
        )


@task(queue='collection_normal')
def create_google_calendar_event_with_single_method(**kwargs):
    fn_name = 'create_google_calendar_event_with_single_method'
    retries = create_google_calendar_event_with_single_method.request.retries
    account_payment_id = kwargs.get('account_payment_id')
    action_log = kwargs.get('action_log')
    dpd = kwargs.get('dpd')
    timeout = kwargs.get('timeout', 120)
    is_ptp = kwargs.get('is_ptp', False)
    logger.info({
        'action': fn_name,
        'message': 'task_begin',
        'timeout': timeout,
        'account_payment_id': account_payment_id,
    })
    try:
        service, sender, calendar_collection = get_google_calendar_service(
            dpd=dpd, timeout=timeout, is_ptp=is_ptp, account_payment_id=account_payment_id
        )

        if not service:
            logger.info(
                {
                    'action': fn_name,
                    'message': 'service google calendar not available',
                }
            )
            return

        today = timezone.localtime(timezone.now())
        dpd_object = today + timedelta(days=dpd)
        account_payment = AccountPayment.objects.get_or_none(pk=account_payment_id)
        mapping_data_google_calendar_single(
            account_payment, dpd_object, service, sender, calendar_collection, action_log
        )
        logger.info(
            {
                'action': fn_name,
                'timeout': timeout,
                'account_payment_id': account_payment_id,
                'message': 'Event created with single method',
            }
        )
    except Exception as error:
        logger.error(
            {
                'action': fn_name,
                'timeout': timeout,
                'account_payment_id': account_payment_id,
                'message': str(error),
            }
        )
        if retries >= create_google_calendar_event_with_single_method.max_retries:
            get_julo_sentry_client().captureException()
            return

        raise create_google_calendar_event_with_single_method.retry(
            countdown=300, exc=error, max_retries=3,
            kwargs={
                'account_payment_id': account_payment_id,
                'action_log': action_log,
                'dpd': dpd,
                # add 20 sec each retries
                'timeout': timeout + (20 * retries),
                'is_ptp': is_ptp,
            }
        )


@task(queue='collection_normal')
def create_google_calendar_event(**kwargs):
    fn_name = 'create_google_calendar_event'
    retries = create_google_calendar_event.request.retries
    account_payment_ids = kwargs.get('account_payment_ids')
    calendar_parameter_id = kwargs.get('calendar_parameter_id')
    action_log = kwargs.get('action_log')
    dpd = kwargs.get('dpd')
    timeout = kwargs.get('timeout', 120)
    is_ptp = kwargs.get('is_ptp', False)
    logger.info(
        {
            'action': fn_name,
            'timeout': timeout,
            'account_payment_ids': account_payment_ids,
            'message': 'task_begin',
        }
    )

    try:
        service, sender, calendar_collection = get_google_calendar_service(
            dpd=dpd,
            timeout=timeout,
            is_ptp=is_ptp,
        )

        if not service:
            logger.info(
                {
                    'action': fn_name,
                    'message': 'service google calendar not available',
                }
            )
            return

        today = timezone.localtime(timezone.now())
        dpd_object = today + timedelta(days=dpd)
        account_payments = AccountPayment.objects.filter(pk__in=account_payment_ids)
        calendar_paremeter = CollectionCalendarsParameter.objects.filter(
            pk=calendar_parameter_id
        ).last()
        mapping_data_google_calendar_event(
            account_payments,
            calendar_paremeter,
            dpd_object,
            action_log,
            service,
            sender,
            calendar_collection,
            is_ptp,
        )
        logger.info(
            {
                'action': fn_name,
                'timeout': timeout,
                'account_payment_ids': account_payment_ids,
                'message': 'Event created',
            }
        )
    except Exception as error:
        logger.error(
            {
                'action': fn_name,
                'timeout': timeout,
                'account_payment_ids': account_payment_ids,
                'message': str(error),
            }
        )
        if retries >= create_google_calendar_event.max_retries:
            get_julo_sentry_client().captureException()
            return

        raise create_google_calendar_event.retry(
            countdown=300, exc=error, max_retries=3,
            kwargs={
                'account_payment_ids': account_payment_ids,
                'action_log': action_log,
                'dpd': dpd,
                'calendar_parameter_id': calendar_parameter_id,
                # add 20 sec each retries
                'timeout': timeout + (20 * retries),
                'is_ptp': is_ptp,
            }
        )
