import time
import logging

from django.db import connection

from juloserver.application_flow.workflows import JuloOneWorkflowAction
from juloserver.julo.models import Application, FDCInquiry
from juloserver.julo.tasks import run_fdc_request
from juloserver.fdc.constants import FDCStatus

logger = logging.getLogger(__name__)


def resume_application_stuck_105_use_reason_2(application_ids: list) -> None:
    # Fetch all applications in a single query
    applications = Application.objects.filter(id__in=application_ids)

    # Create FDCInquiry objects in bulk
    fdc_inquiries = []
    for application in applications.iterator():
        fdc_inquiry = FDCInquiry(
            application_id=application.id,
            nik=application.ktp,
            application_status_code=application.status,
            customer_id=application.customer.id,
        )
        fdc_inquiries.append(fdc_inquiry)

    # Bulk create FDCInquiry objects
    FDCInquiry.objects.bulk_create(fdc_inquiries)

    # Prepare data for async tasks in bulk
    fdc_inquiry_data_list = []
    for fdc in fdc_inquiries:
        fdc_inquiry_data_list.append({'id': fdc.id, 'nik': fdc.nik})
    fdc_reason = 2

    # Process in batches to avoid memory issues
    for fdc_inquiry_data in fdc_inquiry_data_list:
        run_fdc_request.apply_async(
            (
                fdc_inquiry_data,
                fdc_reason,
                0,
                False,
                "triggered from partnership_manual_fdc_inquiry",
            )
        )

    for application in applications.iterator():
        action = JuloOneWorkflowAction(application, None, None, None, None)
        action.trigger_anaserver_status105()
        time.sleep(50)


def resume_application_stuck_105_error(application_ids: list) -> None:
    applications = Application.objects.filter(id__in=application_ids)
    for application in applications.iterator():
        action = JuloOneWorkflowAction(application, None, None, None, None)
        action.run_fdc_task()
        time.sleep(10)
        action.trigger_anaserver_status105()


def check_application_stuck_105() -> None:
    sql_query = """
    select cs.score,a.cdate,a.application_id,a.partner_id,pwmr.*
    from ops.application a
    left join ops.credit_score cs on cs.application_id = a.application_id
    left join ana.pd_web_model_result pwmr on pwmr.application_id = a.application_id
    where a.application_status_code = 105 and (cs.score is null or score not in ('C', '--'))
    and a.partner_id is not null
    and product_line_code = 1
    order by a.cdate desc
    """
    list_application_stuck_105 = []
    with connection.cursor() as cursor:
        cursor.execute(sql_query)
        columns = [col[0] for col in cursor.description]
        rows = cursor.fetchall()
        # Convert rows to a list of application_ids
        list_application_stuck_105 = [
            row[columns.index('application_id')]
            for row in rows
            if row[columns.index('application_id')] is not None
        ]

    if not list_application_stuck_105:
        logger.info(
            {
                "action": "check_application_stuck_105",
                "message": "no application stuck 105",
            }
        )
        return

    """
        Filter the FDCInquiry objects based on status PLEASE_USE_REASON_2
    """
    fdc_inquiries_fail_please_use_reason_2 = FDCInquiry.objects.filter(
        application_id__in=list_application_stuck_105,
        inquiry_reason='1 - Applying loan via Platform',
        inquiry_status='pending',
        status=FDCStatus.PLEASE_USE_REASON_2,
    ).order_by('application_id', '-inquiry_date')
    latest_fdc_inquiry_by_application = fdc_inquiries_fail_please_use_reason_2.distinct(
        'application_id'
    )
    list_application_fdc_inquiries_fail_please_use_reason_2 = list(
        latest_fdc_inquiry_by_application.values_list('application_id', flat=True)
    )
    if list_application_fdc_inquiries_fail_please_use_reason_2:
        logger.info(
            {
                "action": "check_application_stuck_105",
                "message": "Start resume_application_stuck_stuck_105_use_reason_2",
            }
        )
        resume_application_stuck_105_use_reason_2(
            list_application_fdc_inquiries_fail_please_use_reason_2
        )

    """
        Filter the FDCInquiry objects based on status ERROR
    """
    fdc_inquiries_fail_error = FDCInquiry.objects.filter(
        application_id__in=list_application_stuck_105,
        inquiry_reason='1 - Applying loan via Platform',
        inquiry_status='error',
    ).order_by('application_id', '-inquiry_date')
    latest_fdc_inquiry_by_application = fdc_inquiries_fail_error.distinct('application_id')
    list_application_fdc_inquiries_fail_error = list(
        latest_fdc_inquiry_by_application.values_list('application_id', flat=True)
    )
    if list_application_fdc_inquiries_fail_error:
        logger.info(
            {
                "action": "check_application_stuck_105",
                "message": "Start resume_application_stuck_stuck_105_error",
            }
        )
        resume_application_stuck_105_error(list_application_fdc_inquiries_fail_error)

    return
