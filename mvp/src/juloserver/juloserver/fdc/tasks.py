import logging
from celery import task
from dateutil.relativedelta import relativedelta
from django.conf import settings
from django.db.models import Count
from django.utils import timezone
from django.db.models import Q

from juloserver.fdc.constants import FDCStatus
from juloserver.fdc.services import (
    download_outdated_loans_from_fdc,
    download_result_from_fdc,
    download_statistic_data_from_fdc,
    upload_loans_data_to_fdc,
    run_fdc_inquiry_upload,
)
from juloserver.julo.models import (
    Application,
    FDCInquiry,
    FDCRiskyHistory,
)
from juloserver.julo.statuses import ApplicationStatusCodes
from juloserver.julo.utils import post_anaserver
from juloserver.monitors.notifications import notify_failure
from juloserver.julo.constants import UploadAsyncStateStatus, UploadAsyncStateType
from juloserver.julo.models import UploadAsyncState

logger = logging.getLogger(__name__)


@task(name='trigger_download_outdated_loans_from_fdc')
def trigger_download_outdated_loans_from_fdc():
    download_outdated_loans_from_fdc()


@task(name='trigger_download_statistic_from_fdc')
def trigger_download_statistic_from_fdc():
    download_statistic_data_from_fdc()


@task(name='trigger_download_result_fdc')
def trigger_download_result_fdc():
    download_result_from_fdc()


@task(name='trigger_upload_loans_data_to_fdc', queue='lower')
def trigger_upload_loans_data_to_fdc():
    upload_loans_data_to_fdc()


@task(name='alert_unexpected_status_fdc_api')
def alert_unexpected_status_fdc_api():
    time_now = timezone.localtime(timezone.now())
    last_three_hours = time_now - relativedelta(hours=3)
    # exclude status (null, Found, Not Found)
    fdc_unexpected_statuses = (
        FDCInquiry.objects.filter(
            status__isnull=False, cdate__gte=last_three_hours, cdate__lte=time_now
        )
        .exclude(Q(status__iexact=FDCStatus.FOUND) | Q(status__iexact=FDCStatus.NOT_FOUND))
        .values('status')
        .annotate(total=Count('status'))
        .values('status', 'total')
    )
    if len(fdc_unexpected_statuses) == 0:
        logger.info(
            {
                "action": "alert_unexpected_status_FDC_api",
                "message": "theres no unexpected status",
                "now": time_now,
                "last_three_hours": last_three_hours,
            }
        )
        return

    statuses_message = []
    for unexpected_status in fdc_unexpected_statuses:
        formated_message = "`{}` : {}".format(
            unexpected_status['status'], unexpected_status['total']
        )
        statuses_message.append(formated_message)

    message = "Failures in inquiries to FDC API => {}".format(' ,'.join(statuses_message))
    if settings.ENVIRONMENT != 'prod':
        message = "Testing Purpose from {} \n {}".format(settings.ENVIRONMENT, message)

    notify_failure(message, channel='#fdc', label_env=True)


@task(queue='application_normal')
def monitor_fdc_inquiry_job(application_id):
    fdc_inquiry_done = FDCInquiry.objects.filter(
        application_id=application_id, inquiry_status__in=['success', 'not found']
    ).exists()
    if fdc_inquiry_done:
        return

    application = Application.objects.get(pk=application_id)
    if (
        application.application_status_id == ApplicationStatusCodes.FORM_PARTIAL
        and application.is_regular_julo_one()
        and not hasattr(application, 'creditscore')
    ):
        post_anaserver('/api/amp/v1/combined-form/', json={'application_id': application_id})


@task(queue='collection_low')
def j1_record_fdc_risky_history(application_id, is_fdc_risky):
    logger.info(
        {
            "action": "j1_record_fdc_risky_history",
            "message": "start j1 record fdc risky history",
            "data": {
                'application_id': application_id,
                'is_fdc_risky': is_fdc_risky,
            },
        }
    )
    application = Application.objects.get_or_none(pk=application_id)
    if not application or not application.is_julo_one():
        logger.info(
            {
                "action": "j1_record_fdc_risky_history",
                "message": "application is null or is not j1 workflow",
                "data": {
                    'application_id': application_id,
                    'is_fdc_risky': is_fdc_risky,
                },
            }
        )
        return
    account = application.account
    if not account:
        logger.info(
            {
                "action": "j1_record_fdc_risky_history",
                "message": "application dont have account data",
                "data": {
                    'application_id': application_id,
                    'is_fdc_risky': is_fdc_risky,
                },
            }
        )
        return

    oldest_account_payment = account.get_oldest_unpaid_account_payment()
    FDCRiskyHistory.objects.create(
        application_id=application.id,
        account_id=account.id,
        dpd=oldest_account_payment.dpd if oldest_account_payment else None,
        is_fdc_risky=is_fdc_risky,
    )


@task(name='process_run_fdc_inquiry')
def process_run_fdc_inquiry(upload_async_state_id: int) -> None:
    upload_async_state = UploadAsyncState.objects.filter(
        id=upload_async_state_id,
        task_type=UploadAsyncStateType.RUN_FDC_INQUIRY_CHECK,
        task_status=UploadAsyncStateStatus.WAITING,
    ).first()
    if not upload_async_state or not upload_async_state.file:
        logger.info(
            {
                "action": "process_run_fdc_inquiry",
                "message": "File not found",
                "upload_async_state_id": upload_async_state_id,
            }
        )

        if upload_async_state:
            upload_async_state.update_safely(task_status=UploadAsyncStateStatus.FAILED)

        return

    upload_async_state.update_safely(task_status=UploadAsyncStateStatus.PROCESSING)

    try:
        is_success_all = run_fdc_inquiry_upload(upload_async_state)
        if is_success_all:
            task_status = UploadAsyncStateStatus.COMPLETED
        else:
            task_status = UploadAsyncStateStatus.PARTIAL_COMPLETED
        upload_async_state.update_safely(task_status=task_status)
    except Exception as e:
        logger.exception(
            {
                'module': 'run_fdc_inquiry',
                'action': 'failed_process_run_fdc_inquiry',
                'upload_async_state_id': upload_async_state_id,
                'error': e,
            }
        )
        upload_async_state.update_safely(task_status=UploadAsyncStateStatus.FAILED)
