import json
import os
import tempfile
import pdfkit
import logging
import requests
import math
from time import sleep
from datetime import datetime, time, timedelta

from django.db.models import Prefetch
from django.db import connection
from bulk_update.helper import bulk_update
from celery import task
from django.conf import settings
from django.db import transaction
from django.db.models import Sum, Q
from requests.exceptions import Timeout
from typing import Optional
from django.utils import timezone
from dateutil.relativedelta import relativedelta

from juloserver.account.models import AccountTransaction
from juloserver.grab.clients.clients import GrabClient, send_grab_api_timeout_alert_slack
from juloserver.grab.models import (
    GrabProgramInterest,
    GrabProgramFeatureSetting,
    GrabLoanData,
    GrabTransactions,
    GrabPaymentData,
    GrabAPILog,
    GrabLoanOffer,
    GrabPaymentPlans
)
from juloserver.grab.utils import (
    GrabSqlUtility,
    send_sms_to_dax_pass_3_max_creditors,
    is_application_reached_180_before,
    GrabUtils,
)
from juloserver.julo.models import (
    Application,
    FeatureSetting,
    Loan,
    ApplicationCheckList,
    Payment,
    Partner,
    LoanHistory,
    ApplicationNote,
    StatusLookup,
    ApplicationHistory,
    Workflow,
    Customer,
    Image,
    SmsHistory,
    EmailHistory,
    FDCInquiry
)
from juloserver.account.models import Account
from juloserver.grab.clients.request_constructors import GrabRequestDataConstructor
from juloserver.julo.constants import FeatureNameConst, WorkflowConst
from rest_framework import status
from juloserver.grab.exceptions import (
    GrabApiException,
    GrabLogicException,
    GrabHaltResumeError,
    GrabServiceApiException,
)
from juloserver.grab.constants import (
    grab_status_mapping_statuses,
    SLACK_CAPTURE_FAILED_CHANNEL,
    GRAB_BULK_UPDATE_SIZE,
    GRAB_FILE_TRANSFER_LOAN_LIMIT,
    GRAB_FILE_TRANSFER_DAILY_TRANSACTION_LIMIT,
    AccountHaltStatus,
    FeatureSettingParameters,
    GRAB_ACCOUNT_LOOKUP_NAME,
    GrabSMSTemplateCodes,
    GrabEmailTemplateCodes,
    GRAB_MAX_CREDITORS_REACHED_ERROR_MESSAGE,
    GRAB_AUTH_FAILED_3_MAX_CREDS_ERROR_MESSAGE,
    GRAB_BLACKLIST_CUSTOMER,
    GrabApiLogConstants,
    GrabMasterLockConstants,
    ApplicationStatus
)
from juloserver.julo.statuses import ApplicationStatusCodes, LoanStatusCodes, PaymentStatusCodes
from juloserver.julo.application_checklist import application_checklist
from juloserver.julo.product_lines import ProductLineCodes
from juloserver.grab.clients.paths import GrabPaths
from django.utils import timezone
from croniter import croniter
from juloserver.grab.models import (
    GrabExcludedOldRepaymentLoan,
    GrabAsyncAuditCron,
    GrabCustomerData,
)
from juloserver.monitors.notifications import send_message_normal_format
from juloserver.julo.exceptions import JuloException
from juloserver.julo.models import Document, ApplicationHistory
from juloserver.grab.constants import GrabWriteOffStatus, GrabAuthAPIErrorCodes
from juloserver.streamlined_communication.constant import CommunicationPlatform
from juloserver.streamlined_communication.models import (
    InfoCardButtonProperty,
    InfoCardProperty,
    StreamlinedCommunication,
    StreamlinedMessage,
)
from juloserver.account_payment.services.earning_cashback import make_cashback_available
from juloserver.julo.clients import get_julo_sms_client, get_julo_email_client
from juloserver.urlshortener.services import shorten_url
from juloserver.julo.services2.sms import create_sms_history
from juloserver.julo.utils import format_e164_indo_phone_number
from juloserver.loan.constants import FDCUpdateTypes
from juloserver.moengage.utils import chunks
from juloserver.grab.services import fdc as grab_fdc
from juloserver.grab.services.crs_failed_validation_services import CRSFailedValidationService
from http import HTTPStatus

logger = logging.getLogger(__name__)


@task(name='trigger_application_creation_grab_api', queue='grab_global_queue')
def trigger_application_creation_grab_api(application_id):
    application = Application.objects.get(id=application_id)
    try:
        response = GrabClient.fetch_application_submission_log(
            application_id=application.id,
            customer_id=application.customer.id
        )

        if not isinstance(response, requests.Response):
            GrabClient.submit_application_creation(
                application_id=application.id,
                customer_id=application.customer.id
            )
    except Timeout as e:
        default_url = GrabPaths.APPLICATION_CREATION
        if e.response:
            send_grab_api_timeout_alert_slack.delay(
                response=e.response,
                uri_path=e.request.url if e.request else default_url,
                application_id=application.id,
                customer_id=application.customer.id,
            )
        else:
            send_grab_api_timeout_alert_slack.delay(
                uri_path=e.request.url if e.request else default_url,
                application_id=application.id,
                customer_id=application.customer.id,
                err_message=str(e) if e else None,
            )


@task(name='grab_auto_apply_loan_task', queue='grab_global_queue')
def grab_auto_apply_loan_task(customer_id, program_id, application_id, bypass=True):
    from juloserver.grab.services.services import GrabLoanService, GrabAPIService, update_grab_limit

    logger.info(
        {
            "action": "grab_auto_apply_loan_task",
            "message": "triggered",
            "customer_id": customer_id,
            "program_id": program_id,
            "application_id": application_id,
        }
    )

    # we need to check if the user have grab loan offer data or not
    # if not, we immediately request it.
    customer = Customer.objects.get_or_none(id=customer_id)
    if not customer:
        logger.exception(
            {
                "action": "grab_auto_apply_loan_task",
                "message": "customer with id {} doesn't exists".format(customer_id),
            }
        )
        return
    grab_loan_service = GrabLoanService()
    grab_customer_data = grab_loan_service.get_valid_grab_customer_data(customer)
    grab_loan_offer = grab_loan_service.get_grab_loan_offer_data(
        grab_customer_data.id, program_id, False
    )
    if not grab_loan_offer:
        grab_response = GrabClient.get_loan_offer(
            phone_number=grab_customer_data.phone_number, customer_id=grab_customer_data.customer_id
        )
        grab_loan_service.parse_loan_offer(grab_response, grab_customer_data)

    account = Account.objects.filter(
        customer=customer, account_lookup__workflow__name=WorkflowConst.GRAB
    ).last()
    if not account:
        logger.exception(
            {
                "action": "grab_auto_apply_loan_task",
                "message": "grab account with customer id {} doesn't exists".format(customer_id),
            }
        )
        return
    if not bypass:
        update_grab_limit(account, program_id)

    grab_auto_apply_loan_task_subtask.apply_async(args=(customer.id, program_id, application_id))


@task(name='grab_auto_apply_loan_task_subtask', queue='grab_global_queue')
def grab_auto_apply_loan_task_subtask(
    customer_id,
    program_id,
    application_id,
    retry_count=0,
    max_retry=3,
    delay=300,
):
    logger.info(
        {
            "action": "grab_auto_apply_loan_task_subtask",
            "message": "triggered",
            "customer_id": customer_id,
            "program_id": program_id,
            "application_id": application_id,
        }
    )

    try:
        customer = Customer.objects.get(id=customer_id)
    except Customer.DoesNotExist:
        logger.error({"message": "Customer not found", "customer_id": customer_id})
        return

    token = customer.user.auth_expiry_token.key
    headers = {'Authorization': f'Token {token}'}
    payload = {"program_id": program_id, "application_id": application_id}

    try:
        response = requests.post(
            url=f"{settings.GRAB_SERVICE_BASE_URL}/api/partner/grab/loan-creation-request",
            headers=headers,
            json=payload,
        )
    except requests.RequestException as e:
        logger.error(
            {
                "action": "grab_auto_apply_loan_task_subtask",
                "message": "request failed",
                "error": str(e),
            }
        )
        if retry_count < max_retry:
            retry_count += 1
            logger.info(
                {
                    "action": "grab_auto_apply_loan_task_subtask",
                    "message": "retrying after exception",
                    "retry_count": retry_count,
                }
            )
            # Schedule a retry
            grab_auto_apply_loan_task_subtask.apply_async(
                args=(customer_id, program_id, application_id, retry_count),
                eta=timezone.localtime(timezone.now()) + timedelta(seconds=delay),
            )
        return

    # Handle response
    if response.status_code in {
        HTTPStatus.REQUEST_TIMEOUT,
        HTTPStatus.GATEWAY_TIMEOUT,
        HTTPStatus.INTERNAL_SERVER_ERROR,
    }:
        if retry_count < max_retry:
            retry_count += 1
            logger.info(
                {
                    "action": "grab_auto_apply_loan_task_subtask",
                    "message": "retrying due to server error",
                    "retry_count": retry_count,
                    "response_status": response.status_code,
                }
            )
            grab_auto_apply_loan_task_subtask.apply_async(
                args=(customer_id, program_id, application_id, retry_count),
                eta=timezone.localtime(timezone.now()) + timedelta(seconds=delay),
            )
        else:
            logger.warning(
                {
                    "action": "grab_auto_apply_loan_task_subtask",
                    "message": "max retries reached",
                    "response_status": response.status_code,
                }
            )
    elif response.status_code == HTTPStatus.BAD_REQUEST:
        errors = response.json().get("errors", "Unknown errors")
        logger.error(
            {
                "action": "grab_auto_apply_loan_task_subtask",
                "message": "bad request error",
                "errors": errors,
            }
        )
        raise GrabServiceApiException(errors)
    else:
        logger.info(
            {
                "action": "grab_auto_apply_loan_task_subtask",
                "message": "successfully called loan creation request",
                "payload": payload,
                "response_status": response.status_code,
            }
        )


@task(name='trigger_application_updation_grab_api', queue='grab_global_queue')
def trigger_application_updation_grab_api(application_id):
    application = Application.objects.get(id=application_id)
    grab_status_mapping = None
    for grab_status in grab_status_mapping_statuses:
        if application.application_status_id == grab_status.list_code:
            if application.application_status_id != ApplicationStatusCodes.LOC_APPROVED:
                grab_status_mapping = grab_status.mapping_status
            else:
                if Loan.objects.filter(
                    account=application.account).exclude(
                    loan_status__in=[
                        LoanStatusCodes.CURRENT, LoanStatusCodes.LOAN_1DPD,
                        LoanStatusCodes.LOAN_5DPD, LoanStatusCodes.LOAN_30DPD,
                        LoanStatusCodes.LOAN_60DPD, LoanStatusCodes.LOAN_90DPD,
                        LoanStatusCodes.LOAN_120DPD, LoanStatusCodes.LOAN_150DPD,
                        LoanStatusCodes.LOAN_180DPD, LoanStatusCodes.RENEGOTIATED,
                        241
                    ]
                ).exists():
                    additional_check = 'Inactive Loan'
                else:
                    additional_check = 'No Inactive Loan'
                if grab_status.additional_check == additional_check:
                    grab_status_mapping = grab_status.mapping_status
    if grab_status_mapping is None:
        return
    try:
        response = GrabClient.submit_application_updation(
            application_id=application.id,
            customer_id=application.customer.id
        )
        if response and response.status_code not in {status.HTTP_200_OK, status.HTTP_201_CREATED}:
            raise GrabApiException("ApplicationData Api failed for "
                                   "application {}".format(application.id))
    except Timeout as e:
        default_url = GrabPaths.APPLICATION_UPDATION
        if e.response:
            send_grab_api_timeout_alert_slack.delay(
                response=e.response,
                uri_path=e.request.url if e.request else default_url,
                application_id=application.id,
                customer_id=application.customer.id
            )
        else:
            send_grab_api_timeout_alert_slack.delay(
                uri_path=e.request.url if e.request else default_url,
                application_id=application.id,
                customer_id=application.customer.id,
                err_message=str(e) if e else None
            )


@task(name="trigger_push_notification_grab", queue='grab_global_queue')
def trigger_push_notification_grab(application_id=None, loan_id=None):
    feature_setting = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.GRAB_PUSH_NOTIFICATION,
        is_active=True
    ).last()
    if not feature_setting:
        return
    if application_id:
        application = Application.objects.filter(id=application_id).last()
        customer = application.customer
        if application.application_status_id not in feature_setting.parameters['applications']:
            return
    elif loan_id:
        loan = Loan.objects.filter(id=loan_id).last()
        customer = loan.customer
        if loan.loan_status.status_code not in feature_setting.parameters['loans']:
            return
    else:
        return
    logger.info({
        "action": "trigger_push_notification_grab",
        "application_id": application_id,
        "loan_id": loan_id,
    })
    try:
        GrabClient.trigger_push_notification(
            application_id=application_id, customer_id=customer.id, loan_id=loan_id)
    except Timeout as e:
        default_url = GrabPaths.PUSH_NOTIFICATION
        if e.response:
            send_grab_api_timeout_alert_slack.delay(
                response=e.response,
                uri_path=e.request.url if e.request else default_url,
                application_id=application.id if application else None,
                customer_id=application.customer.id if application else None
            )
        else:
            send_grab_api_timeout_alert_slack.delay(
                uri_path=e.request.url if e.request else default_url,
                application_id=application.id if application else None,
                customer_id=application.customer.id if application else None,
                err_message=str(e) if e else None
            )


@task(name="trigger_action_handler_124_to_190_grab", queue='grab_global_queue')
def trigger_action_handler_124_to_190_grab(application_id=None):
    from juloserver.grab.services.services import process_grab_bank_validation_v2
    if not application_id:
        return
    logger.info({
        "task_action": "trigger_action_handler_124_to_190_grab",
        "application_id": application_id
    })
    with transaction.atomic():
        process_grab_bank_validation_v2(application_id)


@task(name="create_application_checklist_grab", queue="normal")
def create_application_checklist_grab():
    applications = Application.objects.prefetch_related(
        'applicationchecklist_set').select_related('customer').filter(
        product_line_id=ProductLineCodes.GRAB)
    # create application checklist data for the first time at 110
    bulk_application_checklist = list()
    for application in applications:
        if application.applicationchecklist_set.all().exists():
            continue
        for field in application_checklist:
            data_to_create = {
                'application': application,
                'field_name': field
            }
            bulk_application_checklist.append(ApplicationCheckList(**data_to_create))
    ApplicationCheckList.objects.bulk_create(bulk_application_checklist, batch_size=30)


@task(queue='grab_deduction_main_queue')
def cron_trigger_grab_deduction_v2():
    # check feature setting is activated or not
    deduction_feature_setting = FeatureSetting.objects.get_or_none(
        feature_name=FeatureNameConst.GRAB_DEDUCTION_SCHEDULE, is_active=True)
    if not deduction_feature_setting:
        logger.info({
            "action": "cron_trigger_grab_deduction_v2",
            "message": "grab deduction feature setting doesn't exist or inactive"
        })
        return

    if deduction_feature_setting.parameters:
        schedule_list = deduction_feature_setting.parameters.get("schedule")
        if not schedule_list:
            logger.exception({
                "action": "trigger_grab_deduction_v2",
                "error": "grab deduction feature setting doesn't have schedule"
            })
            raise GrabLogicException("Scheduled List Missing")

        schedule_time_list = []
        schedule_cron_time_list = []
        try:
            # convert time string to datetime.time. (e.g. "10:00" -> datetime.time(10, 00))
            for time_scheduled in schedule_list:
                schedule_time = datetime.strptime(time_scheduled, '%H:%M').time()
                schedule_time_list.append(schedule_time)
        except Exception as e:
            logger.exception({
                "action": "trigger_grab_deduction_v2",
                "error": e
            })
            raise GrabLogicException(str(e))

        # convert datetime.time to cron format. (e.g. datetime.time(10, 00) -> '0 10 * * *')
        for stime in schedule_time_list:
            cron_time = f'{stime.minute} {stime.hour} * * *'
            schedule_cron_time_list.append(cron_time)

        midnight_today = timezone.localtime(
            datetime.combine(timezone.localtime(timezone.now()).date(), time()))

        for idx, cron_t in enumerate(schedule_cron_time_list):
            croniter_data = croniter(cron_t, midnight_today)
            while True:
                next_schedule = croniter_data.get_next(datetime)
                if next_schedule.day != midnight_today.day or next_schedule.month != midnight_today.month:
                    break

                if next_schedule < timezone.localtime(timezone.now()):
                    continue

                batch_id = "batch-{batch_number} {timestamp}".format(
                    batch_number=idx, timestamp=next_schedule.strftime('%Y-%m-%d %H:%M'))

                logger.info({
                    "action": "trigger_grab_deduction_v2",
                    "message": f"call grab deduction at {timezone.localtime(timezone.now())}",
                    "cron_t": cron_t,
                    "batch_id": batch_id,
                    "next_schedule": next_schedule,
                    "current_time": timezone.localtime(timezone.now())
                })
                trigger_deduction_main_function.apply_async((batch_id,), eta=next_schedule)


@task(queue="grab_deduction_main_queue")
def trigger_deduction_main_function(batch_id):
    deduction_feature_setting = FeatureSetting.objects.get_or_none(
        feature_name=FeatureNameConst.GRAB_DEDUCTION_SCHEDULE, is_active=True)
    if not deduction_feature_setting:
        logger.info({
            "action": "trigger_deduction_main_function",
            "message": "grab deduction feature setting doesn't exist or inactive"
        })
        return
    if deduction_feature_setting.parameters:
        complete_rollover_flag = deduction_feature_setting.parameters.get("complete_rollover", False)
        if complete_rollover_flag:
            loan_ids = Loan.objects.filter(
                account__account_lookup__workflow__name=WorkflowConst.GRAB,
                loan_status_id__in={
                    LoanStatusCodes.CURRENT, LoanStatusCodes.LOAN_1DPD,
                    LoanStatusCodes.LOAN_5DPD, LoanStatusCodes.LOAN_30DPD,
                    LoanStatusCodes.LOAN_60DPD, LoanStatusCodes.LOAN_90DPD,
                    LoanStatusCodes.LOAN_120DPD, LoanStatusCodes.LOAN_150DPD,
                    LoanStatusCodes.LOAN_180DPD
                }
            ).values_list('id', flat=True)
        else:
            loan_ids = []
            program_feature_setting = GrabProgramFeatureSetting.objects.filter(
                feature_setting=deduction_feature_setting,
                is_active=True
            )
            program_interest_id = [program.program_id_id for program in program_feature_setting]
            program_interest_list = GrabProgramInterest.objects.filter(
                pk__in=program_interest_id
            ).values('program_id', 'interest')
            for program_interest in program_interest_list:
                grab_loan_datas = GrabLoanData.objects.filter(
                    program_id=program_interest.get('program_id'),
                    selected_interest=program_interest.get('interest'),
                    loan_id__isnull=False,
                    loan__loan_status_id__in={
                        LoanStatusCodes.CURRENT, LoanStatusCodes.LOAN_1DPD,
                        LoanStatusCodes.LOAN_5DPD, LoanStatusCodes.LOAN_30DPD,
                        LoanStatusCodes.LOAN_60DPD, LoanStatusCodes.LOAN_90DPD,
                        LoanStatusCodes.LOAN_120DPD, LoanStatusCodes.LOAN_150DPD,
                        LoanStatusCodes.LOAN_180DPD
                    }
                ).values_list('loan_id', flat=True)
                loan_ids.extend(grab_loan_datas)

        today = timezone.localtime(timezone.now())
        pending_loan_ids = Payment.objects.filter(
            due_date__lte=today,
            is_restructured=False,
            loan_id__in=loan_ids,
            loan__loan_status_id__in={
                LoanStatusCodes.CURRENT,
                LoanStatusCodes.LOAN_1DPD,
                LoanStatusCodes.LOAN_5DPD,
                LoanStatusCodes.LOAN_30DPD,
                LoanStatusCodes.LOAN_60DPD,
                LoanStatusCodes.LOAN_90DPD,
                LoanStatusCodes.LOAN_120DPD,
                LoanStatusCodes.LOAN_150DPD,
                LoanStatusCodes.LOAN_180DPD
            },
            payment_status_id__in={
                PaymentStatusCodes.PAYMENT_NOT_DUE,
                PaymentStatusCodes.PAYMENT_DUE_IN_3_DAYS,
                PaymentStatusCodes.PAYMENT_DUE_IN_1_DAYS,
                PaymentStatusCodes.PAYMENT_DUE_TODAY,
                PaymentStatusCodes.PAYMENT_1DPD,
                PaymentStatusCodes.PAYMENT_5DPD,
                PaymentStatusCodes.PAYMENT_30DPD,
                PaymentStatusCodes.PAYMENT_60DPD,
                PaymentStatusCodes.PAYMENT_90DPD,
                PaymentStatusCodes.PAYMENT_120DPD,
                PaymentStatusCodes.PAYMENT_150DPD,
                PaymentStatusCodes.PAYMENT_180DPD,
            }
        ).values_list('loan_id', flat=True)
        # remove the duplicate loan ids
        pending_loan_ids = set(pending_loan_ids.iterator())
        for pending_loan_id in pending_loan_ids:
            trigger_deduction_api_cron.delay(pending_loan_id, batch_id)


@task(queue="grab_deduction_sub_queue")
def trigger_deduction_api_cron(loan_id, batch_id):
    unique_txn_id = GrabRequestDataConstructor.create_repayment_transaction_id()
    grab_txn = GrabTransactions.objects.create(
        id=unique_txn_id,
        batch=batch_id,
        status=GrabTransactions.INITITATED,
        loan_id=loan_id
    )
    logger.info({
        "action": "trigger_deduction_api_cron",
        "loan_id": loan_id,
        "batch_id": batch_id,
        "status": "triggered",
        "grab_txn": grab_txn.id,
        "grab_txn_status": grab_txn.status
    })
    try:
        GrabClient.trigger_repayment_trigger_api(loan_id, grab_txn)
    except Timeout as e:
        # TODO: send to #grab-dev slack as grab timeout error
        grab_txn.status = GrabTransactions.FAILED
        grab_txn.save()
        raise e
    except Exception as e:
        logger.exception({
            "action": "trigger_deduction_api_cron",
            "loan_id": loan_id,
            "batch_id": batch_id,
            "error": str(e)
        })
        grab_txn.status = GrabTransactions.FAILED
        grab_txn.save()
        logger.info({
            "action": "trigger_deduction_api_cron",
            "loan_id": loan_id,
            "batch_id": batch_id,
            "status": "Failed",
            "grab_txn": grab_txn.id,
            "grab_txn_status": grab_txn.status
        })
        raise e


@task(queue="grab_global_queue")
def update_failed_grab_transaction_status():
    """
    Updating all grab transactions which still initiated status and already more than 24 hours created to failed status
    """
    today = timezone.localtime(timezone.now())
    twentyfour_hours_ago = today - timedelta(hours=24)
    grab_txns = GrabTransactions.objects.filter(
        status__in={
            GrabTransactions.INITITATED,
            GrabTransactions.IN_PROGRESS
        },
        cdate__lt=twentyfour_hours_ago
    )

    grab_txn_ids = []
    updated_grab_txns = []
    bulk_update_batch_size = GRAB_BULK_UPDATE_SIZE
    for grab_txn in grab_txns.iterator():
        grab_txn_ids.append(grab_txn.id)
        grab_txn.status = GrabTransactions.EXPIRED
        grab_txn.udate = timezone.localtime(timezone.now())
        updated_grab_txns.append(grab_txn)

        if len(updated_grab_txns) == bulk_update_batch_size:
            """
            avoiding memory spike
            so if we have 1000 data, the bulk update will only processing per GRAB_BULK_UPDATE_SIZE
            and cleared the updated_grab_txns list
            """
            bulk_update(
                updated_grab_txns,
                update_fields=['udate', 'status'],
                batch_size=bulk_update_batch_size,
                using='partnership_grab_db'
            )
            updated_grab_txns = []

    if updated_grab_txns:
        bulk_update(
            updated_grab_txns,
            update_fields=['udate', 'status'],
            using='partnership_grab_db'
        )
        del updated_grab_txns

    logger.info({
        "action": "update_failed_grab_transaction_status",
        "message": f"success updating grab transaction ids ({grab_txn_ids}) to failed status"
    })



@task(queue="grab_global_queue")
def mark_form_partial_expired_grab() -> Optional[None]:

    applications_ids = Application.objects.select_related('workflow').filter(
        application_status_id__lte=ApplicationStatusCodes.FORM_PARTIAL,
        workflow__name=WorkflowConst.GRAB
    ).values_list('id', 'cdate', 'application_status_id')

    for application_id, created_date, application_status_id in applications_ids:
        mark_form_partial_expired_grab_subtask.delay(
            application_id, created_date, application_status_id
        )


@task(queue="grab_global_queue")
def mark_form_partial_expired_grab_subtask(
        application_id: int,
        created_date: datetime,
        application_status_id: int) -> Optional[None]:
    from juloserver.julo.services import process_application_status_change
    one_weeks_ago = timezone.localtime(timezone.now() - relativedelta(days=7))
    logger.info({
        "action": "mark_form_partial_expired_grab_subtask",
        "process": "Triggered",
        "application_id": application_id,
        "created_date": created_date,
        "application_status": application_status_id,
        "created_date <= one_weeks_ago": created_date <= one_weeks_ago
    })
    if application_status_id not in {
        ApplicationStatusCodes.FORM_PARTIAL,
        ApplicationStatusCodes.FORM_CREATED,
        ApplicationStatusCodes.NOT_YET_CREATED
    }:
        return
    if created_date <= one_weeks_ago:  # Compare Created date with Time one week ago
        process_application_status_change(
            application_id, ApplicationStatusCodes.FORM_PARTIAL_EXPIRED, "system_triggered"
        )


@task(queue='grab_deduction_main_queue')
def async_update_grab_excluded_old_repayment_loan() -> None:
    deduction_feature_setting = FeatureSetting.objects.get_or_none(
        feature_name=FeatureNameConst.GRAB_DEDUCTION_SCHEDULE, is_active=True)
    excluded_loan_ids = []
    if deduction_feature_setting and deduction_feature_setting.parameters:
        complete_rollover_flag = deduction_feature_setting.parameters.get("complete_rollover", False)
        if not complete_rollover_flag:
            program_feature_setting_interest_ids = GrabProgramFeatureSetting.objects.filter(
                feature_setting=deduction_feature_setting,
                is_active=True
            ).values_list('program_id', flat=True)

            program_interest_list = GrabProgramInterest.objects.filter(pk__in=program_feature_setting_interest_ids) \
                .values('program_id', 'interest')

            for program_interest in program_interest_list:
                grab_loan_datas = GrabLoanData.objects.select_related(
                    'loan', 'loan__loan_status').filter(
                    program_id=program_interest.get('program_id'),
                    selected_interest=program_interest.get('interest'),
                    loan_id__isnull=False,
                    loan__loan_status_id__in={
                        LoanStatusCodes.CURRENT, LoanStatusCodes.LOAN_1DPD,
                        LoanStatusCodes.LOAN_5DPD, LoanStatusCodes.LOAN_30DPD,
                        LoanStatusCodes.LOAN_60DPD, LoanStatusCodes.LOAN_90DPD,
                        LoanStatusCodes.LOAN_120DPD, LoanStatusCodes.LOAN_150DPD,
                        LoanStatusCodes.LOAN_180DPD
                    }
                ).values_list(
                    'loan_id', flat=True)
                excluded_loan_ids.extend(grab_loan_datas)
            for excluded_loan in excluded_loan_ids:
                grab_excluded_old_repayment_loan, created_flag = \
                    GrabExcludedOldRepaymentLoan.objects.get_or_create(loan_id=excluded_loan)
            GrabExcludedOldRepaymentLoan.objects.exclude(
                loan_id__in=excluded_loan_ids).delete()


@task(queue="grab_global_queue")
def trigger_grab_refinance_email(loan_id):
    from juloserver.grab.communication.email import trigger_sending_email_sphp
    trigger_sending_email_sphp(loan_id)


@task(name="send_grab_failed_deduction_slack", queue="grab_global_queue")
def send_grab_failed_deduction_slack(uri_path=None, slack_channel="#grab-failed-deduction",
                                     msg_header="GRAB Failed Deduction", loan_id=None,
                                     grab_txn_id=None, err_message=None, params=None, msg_type=1):
    """
    msg_type :
        1 : full message type
        2: only env, params and err_message
        3: only env
    """
    env = settings.ENVIRONMENT.upper()
    msg_header = f"\n\n*{msg_header}*"
    msg = "\n\tENV : {}\n\tURL : {}\n\tLoan ID: {}\n\tGrab TXN ID : {}\n\tError Message : {}\n\n".format(
        env, uri_path, loan_id, grab_txn_id, err_message)
    if msg_type == 2:
        msg = "\n\tENV : {}\n\tPARAMS : {}\n\tError Message : {}\n\n".format(env, params,
                                                                             err_message)
    elif msg_type == 3:
        msg = "\n\tENV : {}\n\n".format(env)
    send_message_normal_format(msg_header + msg, slack_channel)


@task(bind=True, max_retries=9, queue="grab_global_queue")
def trigger_submit_grab_disbursal_creation(self, loan_id):
    """
    Task for triggering capture/ disbursement creation to GRAB side
    will have some retry if there is Timeout error with exponential start from 300 secs (5 min)

    param:
        - loan_id (int) : loan id
    """
    try:
        loan = Loan.objects.get(pk=loan_id)
    except Loan.DoesNotExist:
        logger.exception({
            "action": "trigger_submit_grab_disbursal_creation",
            "message": "Loan doesn't exist"
        })
        raise

    application = loan.account.last_application
    try:
        GrabClient.submit_disbursal_creation(disbursement_id=loan.disbursement_id,
                                             loan_id=loan.id,
                                             customer_id=loan.customer.id,
                                             application_id=application.id)
    except Timeout as exc:
        retries = self.request.retries
        if retries >= self.max_retries:
            capture_url = GrabPaths.DISBURSAL_CREATION
            content = json.loads(
                exc.response.content) if exc.response.content else "no content from response"
            send_grab_api_timeout_alert_slack.delay(
                uri_path=exc.request.url if exc.request else capture_url,
                application_id=application.id,
                customer_id=application.customer.id,
                slack_channel=SLACK_CAPTURE_FAILED_CHANNEL,
                loan_id=loan.id,
                phone_number=application.mobile_phone_1,
                err_message=content,
            )
            logger.exception({
                "action": "trigger_submit_grab_disbursal_creation",
                "message": "maximum retry have been reached"
            })
            raise
        raise self.retry(exc=exc, countdown=300 * 2 ** retries)


@task(queue="grab_global_queue")
def trigger_grab_loan_sync_api_async_task(loan_id):
    logger.info({
        'task': 'trigger_grab_loan_sync_api_async_task',
        'message': 'starting_async_task',
        'loan_id': loan_id
    })
    loan = Loan.objects.select_related('account').filter(
        id=loan_id).last()
    if not loan:
        logger.exception({
            'task': 'trigger_grab_loan_sync_api_async_task',
            'exception': 'Loan ID not found for triggering loan_sync_api',
            'loan_id': loan_id
        })
        return
    application = loan.account.application_set.filter(
        workflow__name=WorkflowConst.GRAB,
        application_status_id=ApplicationStatusCodes.LOC_APPROVED
    ).last()
    if not application:
        logger.exception({
            'task': 'trigger_grab_loan_sync_api_async_task',
            'exception': 'Application 190 not found for loan_sync_api',
            'loan_id': loan_id
        })
        return
    try:
        GrabClient.trigger_loan_sync_api(
            loan_id, application_id=application.id,
            customer_id=application.customer.id)
    except Timeout as e:
        default_url = GrabPaths.LOAN_SYNC_API
        if e.response:
            send_grab_api_timeout_alert_slack.delay(
                response=e.response,
                uri_path=e.request.url if e.request else default_url,
                application_id=application.id,
                customer_id=application.customer.id
            )
        else:
            send_grab_api_timeout_alert_slack.delay(
                uri_path=e.request.url if e.request else default_url,
                application_id=application.id,
                customer_id=application.customer.id,
                err_message=str(e) if e else None
            )
    logger.info({
        'task': 'trigger_grab_loan_sync_api_async_task',
        'message': 'exiting_async_task',
        'loan_id': loan_id
    })


@task(queue="grab_global_queue")
def clear_old_grab_transaction_data():
    CUT_OFF_DURATION_IN_DAYS = 60
    GrabTransactions.objects.filter(
        cdate__lte=timezone.localtime(timezone.now() - timedelta(
            days=CUT_OFF_DURATION_IN_DAYS))).delete()


@task(queue="grab_resume_queue")
def populate_active_loan_to_oss_main():
    included_loan_statuses = LoanStatusCodes.grab_current_until_180_dpd() + (
        LoanStatusCodes.FUND_DISBURSAL_ONGOING, LoanStatusCodes.MANUAL_FUND_DISBURSAL_ONGOING,
        LoanStatusCodes.HALT)
    today_date = timezone.localtime(timezone.now()).date()

    # today at 20:00 PM
    today_8_pm = timezone.localtime(
        timezone.now().replace(hour=20, minute=0, second=0, tzinfo=None))
    one_days_ago = today_8_pm - timedelta(days=1)
    paid_off_previous_day_loan_ids = LoanHistory.objects.filter(
        status_new=LoanStatusCodes.PAID_OFF,
        cdate__gte=one_days_ago,
        cdate__lte=today_8_pm
    ).values_list('loan__id', flat=True)
    number_of_active_loans = Loan.objects.filter(
        Q(loan_status__in=included_loan_statuses) | (Q(loan_status=LoanStatusCodes.PAID_OFF) & Q(
            id__in=paid_off_previous_day_loan_ids)),
        product__product_line__product_line_code__in=ProductLineCodes.grab()
    ).count()

    # get limit per file from feature setting
    grab_file_transfer_feature_setting = FeatureSetting.objects.get_or_none(
        feature_name=FeatureNameConst.GRAB_FILE_TRANSFER_CALL, is_active=True)

    loan_limit_per_file = GRAB_FILE_TRANSFER_LOAN_LIMIT
    if grab_file_transfer_feature_setting and grab_file_transfer_feature_setting.parameters:
        loan_limit_per_file = grab_file_transfer_feature_setting.parameters.get(
            FeatureSettingParameters.LOAN_PER_FILE,
            GRAB_FILE_TRANSFER_LOAN_LIMIT)

    number_of_files = 0
    if number_of_active_loans:
        if number_of_active_loans <= loan_limit_per_file:
            number_of_files = 1
        if number_of_active_loans > loan_limit_per_file:
            number_of_files = number_of_active_loans // loan_limit_per_file

            if number_of_active_loans % loan_limit_per_file > 0:
                number_of_files = number_of_files + 1

    send_grab_failed_deduction_slack.delay(
        msg_header="[GRAB File Transfer] Grab file transfer call for loan have a total {} data and will be splitted into {} files, ( limit per file = {} ).".format(
            number_of_active_loans, number_of_files, loan_limit_per_file),
        msg_type=3
    )
    for file_number in range(number_of_files):
        start_index = file_number * loan_limit_per_file
        end_index = ((file_number + 1) * loan_limit_per_file)
        logger.info({
            "action": "populate_active_loan_to_oss_main",
            "start_index": start_index,
            "end_index": end_index,
            "increment": file_number,
        })
        file_name = "loans_{date}_{incr}.json".format(date=today_date, incr=str(file_number + 1))
        GrabAsyncAuditCron.objects.get_or_create(
            cron_file_name=file_name,
            cron_status=GrabAsyncAuditCron.INITIATED,
            event_date=timezone.localtime(timezone.now()).strftime("%Y-%m-%d")
        )
        populate_files_to_oss_task.delay(start_index, end_index, file_name)


@task(queue="grab_resume_queue")
def populate_daily_transaction_to_oss_main():
    # today at 20:00 PM
    today_8_pm = timezone.localtime(
        timezone.now().replace(hour=20, minute=0, second=0, tzinfo=None))
    one_days_ago = today_8_pm - timedelta(days=1)
    number_of_daily_transactions = AccountTransaction.objects.values(
        'payback_transaction__transaction_id',
        'payback_transaction__transaction_date',
        'payback_transaction__loan_id'
    ).annotate(
        total_amount=Sum('payback_transaction__amount'),
        total_late_fee=Sum('towards_latefee'),
        total_interest=Sum('towards_interest'),
        total_principal=Sum('towards_principal')
    ).filter(
        payback_transaction__payback_service='grab',
        payback_transaction__cdate__gte=one_days_ago,
        payback_transaction__cdate__lte=today_8_pm,
        transaction_type='payment'
    ).exclude(
        payback_transaction__transaction_date=None
    ).order_by('payback_transaction__transaction_date').count()

    # get limit per file from feature setting
    grab_file_transfer_feature_setting = FeatureSetting.objects.get_or_none(
        feature_name=FeatureNameConst.GRAB_FILE_TRANSFER_CALL, is_active=True)

    transaction_limit_per_file = GRAB_FILE_TRANSFER_DAILY_TRANSACTION_LIMIT
    if grab_file_transfer_feature_setting and grab_file_transfer_feature_setting.parameters:
        transaction_limit_per_file = grab_file_transfer_feature_setting.parameters.get(
            FeatureSettingParameters.TRANSACTION_PER_FILE,
            GRAB_FILE_TRANSFER_DAILY_TRANSACTION_LIMIT)

    number_of_files = 0
    if number_of_daily_transactions:
        if number_of_daily_transactions <= transaction_limit_per_file:
            number_of_files = 1
        elif number_of_daily_transactions > transaction_limit_per_file:
            number_of_files = number_of_daily_transactions // transaction_limit_per_file

            if number_of_daily_transactions % transaction_limit_per_file > 0:
                number_of_files = number_of_files + 1

    send_grab_failed_deduction_slack.delay(
        msg_header="[GRAB File Transfer] Grab file transfer call for daily transaction have a total {} data and will be splitted into {} files, ( limit per file = {} ).".format(
            number_of_daily_transactions, number_of_files, transaction_limit_per_file),
        msg_type=3
    )
    for file_number in range(number_of_files):
        start_index = file_number * transaction_limit_per_file
        end_index = ((file_number + 1) * transaction_limit_per_file)
        logger.info({
            "action": "populate_daily_transactions_to_oss_main",
            "start_index": start_index,
            "end_index": end_index,
            "increment": file_number,
        })
        today_date = timezone.localtime(timezone.now()).strftime("%Y-%m-%d")
        file_type = GrabAsyncAuditCron.DAILY_TRANSACTIONS
        file_name = "daily_transactions_{date}_{incr}.json".format(date=today_date,
                                                                   incr=str(file_number + 1))
        GrabAsyncAuditCron.objects.get_or_create(
            cron_file_name=file_name,
            cron_status=GrabAsyncAuditCron.INITIATED,
            event_date=today_date,
            cron_file_type=file_type
        )
        populate_files_to_oss_task.delay(start_index, end_index, file_name, file_type)


@task(queue="grab_resume_queue")
def populate_files_to_oss_task(start_index, end_index, file_name,
                               file_type=GrabAsyncAuditCron.LOANS):
    from juloserver.grab.services.services import upload_grab_files_to_oss
    try:
        grab_async_audit_cron = GrabAsyncAuditCron.objects.filter(
            cron_file_type=file_type,
            cron_file_name=file_name,
            cron_status__in=[GrabAsyncAuditCron.INITIATED, GrabAsyncAuditCron.IN_PROGRESS]
        ).last()
        grab_async_audit_cron.cron_status = GrabAsyncAuditCron.IN_PROGRESS
        grab_async_audit_cron.cron_start_time = timezone.localtime(timezone.now())
        grab_async_audit_cron.save(update_fields=['cron_status', 'cron_start_time'])

        logger.info({
            "action": "populate_files_to_oss_task",
            "start_index": start_index,
            "end_index": end_index,
            "file_name": file_name,
            "file_type": file_type,
        })
        upload_grab_files_to_oss(start_index, end_index, file_name, file_type)
    except Exception as e:
        logger.exception({
            "action": "populate_files_to_oss_task",
            "start_index": start_index,
            "end_index": end_index,
            "file_name": file_name,
            "file_type": file_type,
            "error": str(e)
        })
        grab_async_audit_cron = GrabAsyncAuditCron.objects.filter(
            cron_file_type=file_type,
            cron_file_name=file_name,
            cron_status=GrabAsyncAuditCron.IN_PROGRESS
        ).last()
        grab_async_audit_cron.cron_status = GrabAsyncAuditCron.FAILED
        grab_async_audit_cron.cron_end_time = timezone.localtime(timezone.now())
        grab_async_audit_cron.save(update_fields=['cron_status', 'cron_end_time'])


@task(queue='grab_resume_queue')
def cron_trigger_grab_file_transfer():
    # check feature setting is activated or not
    grab_file_transfer_feature_setting = FeatureSetting.objects.get_or_none(
        feature_name=FeatureNameConst.GRAB_FILE_TRANSFER_CALL, is_active=True)
    if not grab_file_transfer_feature_setting:
        logger.info({
            "action": "cron_trigger_grab_file_transfer",
            "message": "grab file transfer feature setting doesn't exist or inactive"
        })
        # alert to slack
        send_grab_failed_deduction_slack.delay(
            msg_header="[GRAB File Transfer] Grab file transfer call feature setting not found / inactive !",
            msg_type=3
        )
        return

    if not grab_file_transfer_feature_setting.parameters:
        logger.info({
            "action": "cron_trigger_grab_file_transfer",
            "message": "grab file transfer feature setting doesn't have parameters"
        })
        # alert to slack
        send_grab_failed_deduction_slack.delay(
            msg_header="[GRAB File Transfer] grab file transfer feature setting doesn't have parameters",
            msg_type=3
        )
        return

    file_transfer_feature_setting_parameters = grab_file_transfer_feature_setting.parameters
    for key in {'populate_daily_txn_schedule', 'populate_loan_schedule', 'loan_per_file',
                'transaction_per_file'}:
        if not file_transfer_feature_setting_parameters.get(key):
            logger.info({
                "action": "cron_trigger_grab_file_transfer",
                "message": "grab file transfer feature setting parameter {} doesn't exist".format(
                    key)
            })
            # alert to slack
            send_grab_failed_deduction_slack.delay(
                msg_header="[GRAB File Transfer] grab file transfer feature setting parameter {} doesn't exist".format(
                    key),
                msg_type=3
            )
            return

    populate_loan_schedule = grab_file_transfer_feature_setting.parameters.get(
        "populate_loan_schedule")
    populate_daily_txn_schedule = grab_file_transfer_feature_setting.parameters.get(
        "populate_daily_txn_schedule")

    if not populate_loan_schedule:
        logger.exception({
            "action": "cron_trigger_grab_file_transfer",
            "error": "grab file transfer feature setting doesn't have populate_loan_schedule"
        })
        return

    if not populate_daily_txn_schedule:
        logger.exception({
            "action": "cron_trigger_grab_file_transfer",
            "error": "grab file transfer feature setting doesn't have populate_daily_txn_schedule"
        })
        return

    try:
        # convert time string to datetime.time. (e.g. "10:00" -> datetime.time(10, 00))
        populate_loan_schedule_time = datetime.strptime(populate_loan_schedule, '%H:%M').time()
        populate_daily_txn_schedule_time = datetime.strptime(populate_daily_txn_schedule,
                                                             '%H:%M').time()

    except Exception as err:
        logger.exception({
            "action": "cron_trigger_grab_file_transfer",
            "error": str(err)
        })
        return

    # convert datetime.time to cron format. (e.g. datetime.time(10, 00) -> '0 10 * * *')
    populate_loan_schedule_cron_time = f'{populate_loan_schedule_time.minute} {populate_loan_schedule_time.hour} * * *'
    populate_daily_txn_schedule_cron_time = f'{populate_daily_txn_schedule_time.minute} {populate_daily_txn_schedule_time.hour} * * *'

    midnight_today = timezone.localtime(
        datetime.combine(timezone.localtime(timezone.now()).date(), time()))

    populate_loan_croniter_data = croniter(populate_loan_schedule_cron_time, midnight_today)
    populate_daily_txn_croniter_data = croniter(populate_daily_txn_schedule_cron_time, midnight_today)
    next_schedule_populate_loan = populate_loan_croniter_data.get_next(datetime)
    next_schedule_populate_daily_txn = populate_daily_txn_croniter_data.get_next(datetime)

    cron_trigger_populate_grab_file_transfer.delay(
        next_schedule_populate_loan,
        midnight_today,
        populate_loan_schedule_cron_time,
        GrabAsyncAuditCron.LOANS
    )

    cron_trigger_populate_grab_file_transfer.delay(
        next_schedule_populate_daily_txn,
        midnight_today,
        populate_daily_txn_schedule_cron_time,
        GrabAsyncAuditCron.DAILY_TRANSACTIONS
    )


@task(queue='grab_resume_queue')
def cron_trigger_populate_grab_file_transfer(next_schedule, midnight_today, cron_time, file_type):
    if next_schedule.day != midnight_today.day or next_schedule.month != midnight_today.month:
        logger.info({
            "action": "cron_trigger_populate_grab_file_transfer",
            "file_type": file_type,
            "error": "day or month doesn't same with next schedule"
        })
        return

    if next_schedule < timezone.localtime(timezone.now()):
        logger.info({
            "action": "cron_trigger_populate_grab_file_transfer",
            "file_type": file_type,
            "error": "next schedule already passed, will triggered next day"
        })
        return

    logger.info({
        "action": "cron_trigger_populate_grab_file_transfer",
        "file_type": file_type,
        "message": f"call populate file transfer at {timezone.localtime(timezone.now())}",
        "cron_time": cron_time,
        "next_schedule": next_schedule,
        "current_time": timezone.localtime(timezone.now())
    })
    if file_type == GrabAsyncAuditCron.LOANS:
        populate_active_loan_to_oss_main.apply_async(eta=next_schedule)
    else:
        populate_daily_transaction_to_oss_main.apply_async(eta=next_schedule)


@task(queue='grab_resume_queue')
def julo_one_generate_auto_lender_agreement_document_grab_script(loan_id):
    from juloserver.followthemoney.tasks import assign_lenderbucket_xid_to_lendersignature
    from juloserver.grab.script import generate_summary_lender_loan_agreement_grab_script
    from juloserver.followthemoney.models import LenderBucket
    loan = Loan.objects.get_or_none(pk=loan_id)

    if not loan:
        raise JuloException("LOAN NOT FOUND")

    lender = loan.lender
    if not lender:
        raise JuloException("LENDER NOT FOUND")

    is_disbursed = False
    if loan.status >= LoanStatusCodes.CURRENT:
        is_disbursed = True

    action_time = timezone.localtime(timezone.now())
    use_fund_transfer = False

    # Handle axiata loan to define transaction time based on
    if loan.is_axiata_loan() or loan.account.is_grab_account():
        if loan.fund_transfer_ts:
            action_time = loan.fund_transfer_ts
        else:
            action_time = loan.cdate

        use_fund_transfer = True

    lender_bucket = LenderBucket.objects.create(
        partner=lender.user.partner,
        total_approved=1,
        total_rejected=0,
        total_disbursement=loan.loan_disbursement_amount,
        total_loan_amount=loan.loan_amount,
        loan_ids={"approved": [loan_id], "rejected": []},
        is_disbursed=is_disbursed,
        is_active=False,
        action_time=action_time,
        action_name='Disbursed',
    )

    # generate summary lla
    assign_lenderbucket_xid_to_lendersignature(
        [loan_id],
        lender_bucket.lender_bucket_xid,
        is_loan=True
    )
    generate_summary_lender_loan_agreement_grab_script(lender_bucket.id, use_fund_transfer)


@task(queue='grab_halt_queue')
def generate_julo_one_loan_agreement_grab_script(loan_id):
    from juloserver.grab.script import get_julo_loan_agreement_template_grab_script
    from juloserver.julo.tasks import upload_document
    loan = Loan.objects.get_or_none(pk=loan_id)
    if not loan:
        return

    try:
        body, agreement_type, lender_signature, borrower_signature = \
            get_julo_loan_agreement_template_grab_script(loan_id)
        if not body:
            raise JuloException('SPHP / SKRTP template is not found.')
        now = timezone.localtime(timezone.now())
        if loan.application and loan.application.product_line_code in ProductLineCodes.axiata():
            application = loan.application
        else:
            application = loan.account.last_application
        filename = '{}_{}_{}_{}.pdf'.format(
            application.fullname,
            loan.loan_xid,
            now.strftime("%Y%m%d"),
            now.strftime("%H%M%S"),
        )
        file_path = os.path.join(tempfile.gettempdir(), filename)

        try:
            import time as time_module
            now = time_module.time()
            pdfkit.from_string(body, file_path)
            time_limit = 2
            elapsed = time_module.time() - now
            if elapsed > time_limit:
                print("ELAPSED GTE TIME_LIMIT")
        except Exception as e:
            print("ERROR ", str(e))
            raise e

        sphp_or_skrtp_julo = Document.objects.create(
            document_source=loan.id,
            document_type='%s_julo' % agreement_type,
            filename=filename,
            loan_xid=loan.loan_xid,
        )
        upload_document(sphp_or_skrtp_julo.id, file_path, is_loan=True)

    except Exception as e:
        print("Error ", str(e))
        raise e


@task(queue="grab_halt_queue")
def trigger_grab_loan_halt_v2(loan_halt_date, loan_resume_date, account_ids=None):
    """
        DOCUMENTATION:
        This task needs to be called first with 2 parameters.
        loan_halt_date -- datetime format
        loan_resume_date -- datetime format

        The flow for the tasks for calling tasks are as follows:
        1. trigger_grab_loan_halt_v2 -- Halt all grab loans.
        2. trigger_grab_loan_resume_v2 -- resumes all loan.
        3. trigger_loan_resume_final_task_v2 -- will be called on the resume date.

        THIS FEATURE IS FOR HALTING ALL LOANS
    """
    from juloserver.grab.services.loan_halt_resume_services import (
        update_loan_halt_and_resume_date,
    )
    if account_ids is None:
        account_ids = []
    from juloserver.loan.services.loan_related import update_loan_status_and_loan_history
    logger.info({
        "task": "trigger_grab_loan_halt_v2",
        "action": "starting_grab_loan_halt_resume",
        "halt_date": loan_halt_date,
        "resume_date": loan_resume_date
    })
    if not account_ids:
        grab_accounts = Account.objects.filter(
            account_lookup__name='GRAB').values_list('id', flat=True)
    else:
        grab_accounts = Account.objects.filter(
            account_lookup__name='GRAB', id__in=account_ids
        ).values_list('id', flat=True)
    grab_loan_data_set = GrabLoanData.objects.only(
        'id', 'loan_id', 'account_halt_status', 'account_halt_info'
    )
    prefetch_grab_loan_data = Prefetch('grabloandata_set', to_attr='grab_loan_data_set',
                                       queryset=grab_loan_data_set)
    join_tables = [prefetch_grab_loan_data]
    active_loans = Loan.objects.prefetch_related(*join_tables).filter(
        account_id__in=grab_accounts,
        loan_status_id__in=set(LoanStatusCodes.grab_above_90_dpd())
    )
    logger.info({
        "task": "trigger_grab_loan_halt_v2",
        "action": "collected_all_active_loans",
        "halt_date": loan_halt_date,
        "resume_date": loan_resume_date,
        "total_no_of_loans": len(active_loans),
        "total_no_of_account": len(grab_accounts)
    })
    try:
        last_loan_id = active_loans.order_by('-pk')[0].pk
    except IndexError as e:
        logger.info({
            "task": "trigger_grab_loan_halt_v2",
            "error": str(e)
        })
        return
    active_loans = active_loans.order_by('pk')
    CHUNK_SIZE = 30
    pk = 0
    while pk < last_loan_id:
        for loan in active_loans.filter(pk__gt=pk)[:CHUNK_SIZE]:
            pk = loan.pk
            with transaction.atomic():
                grab_loan_data = loan.grab_loan_data_set[0]
                update_loan_halt_and_resume_date(
                    grab_loan_data, loan_halt_date, loan_resume_date)
                update_loan_status_and_loan_history(
                    loan.id, LoanStatusCodes.HALT, None, 'loan_halt_triggered')
                grab_loan_data.update_safely(account_halt_status=AccountHaltStatus.HALTED)
    logger.info({
        "task": "trigger_grab_loan_halt_v2",
        "action": "updated_loans_and_grab_loan_data",
    })
    # All Loans are already halted
    for account_id in grab_accounts.iterator():
        trigger_loan_halt_sub_task_v2.delay(account_id, loan_halt_date)


@task(queue="grab_resume_queue")
def trigger_grab_loan_resume_v2(account_ids=None):
    """
        DOCUMENTATION:
        This task needs to be called after loan is halted.
        The halted and resume dates needs to be inputted while halting

        The flow for the tasks for calling tasks are as follows:
        1. trigger_grab_loan_halt_v2 -- Halt all grab loans.
        2. trigger_grab_loan_resume_v2 -- resumes all loan.
        3. trigger_loan_resume_final_task_v2 -- will be called on the resume date.

        THIS FEATURE IS FOR HALTING ALL LOANS
    """
    if account_ids is None:
        account_ids = []
    if not account_ids:
        grab_accounts = Account.objects.filter(
            account_lookup__name='GRAB').values_list('id', flat=True)
    else:
        grab_accounts = Account.objects.filter(
            account_lookup__name='GRAB', id__in=account_ids).values_list('id', flat=True)
    for account_id in grab_accounts.iterator():
        trigger_loan_resume_sub_task_v2.delay(account_id)


@task(queue="grab_halt_queue")
def trigger_loan_halt_sub_task_v2(account_id, loan_halt_date):
    """
        DOCUMENTATION:
        This Task is the subtask for halting.(called by trigger_grab_loan_halt_v2)
        Typically the LOAN is already halted at this stage.


        The flow for the tasks for calling tasks are as follows:
        1. trigger_grab_loan_halt_v2 -- Halt all grab loans.
        2. trigger_grab_loan_resume_v2 -- resumes all loan.
        3. trigger_loan_resume_final_task_v2 -- will be called on the resume date.

        THIS FEATURE IS FOR HALTING AND RESUMING ALL LOANS
    """
    from juloserver.grab.services.loan_halt_resume_services import update_loan_payments_for_loan_halt_v2
    logger.info({
        "task": "trigger_loan_halt_sub_task_v2",
        "account_id": account_id,
        "action": "starting_trigger_loan_halt_account"
    })
    account = Account.objects.get_or_none(pk=account_id)
    if not account:
        raise GrabHaltResumeError("Invalid AccountID: {}".format(account_id))
    grab_loan_data_set = GrabLoanData.objects.only(
        'id', 'loan_id', 'account_halt_status', 'account_halt_info'
    )
    prefetch_grab_loan_data = Prefetch('grabloandata_set', to_attr='grab_loan_data_set',
                                       queryset=grab_loan_data_set)
    join_tables = [prefetch_grab_loan_data]
    loans = account.loan_set.prefetch_related(*join_tables).filter(
        loan_status_id__in=set(LoanStatusCodes.grab_above_90_dpd() + (LoanStatusCodes.HALT,))
    )
    with transaction.atomic():
        for loan in loans:
            logger.info({
                "task": "trigger_loan_halt_sub_task_v2",
                "loan_id": loan.id,
                "action": "starting_loan_updation_pending"
            })
            update_loan_payments_for_loan_halt_v2(loan, loan_halt_date)
        logger.info({
            "task": "trigger_loan_halt_sub_task_v2",
            "action": "updated_all_loan_updation_pending"
        })
        application = Application.objects.only('id').filter(
            account_id=account_id,
            application_status_id=ApplicationStatusCodes.LOC_APPROVED
        ).last()
        if application:
            ApplicationNote.objects.create(
                application_id=application.id,
                note_text='Account has been Halted. Halt-date: ({})'.format(loan_halt_date)
            )
    logger.info({
        "task": "trigger_loan_halt_sub_task_v2",
        "account_id": account_id,
        "action": "ending_trigger_loan_halt_account"
    })


@task(queue="grab_halt_queue")
def update_grab_payment_data_for_halt_resume_v2(loan_id, is_description_flag=False):
    """
        UPDATE ops.grab_payment_data for halted and resumed loans
    """
    logger.info({
        "task": "update_grab_payment_data_for_halt_resume_v2",
        "loan_id": loan_id,
        "is_description_flag": is_description_flag,
        "status": "starting_process"
    })
    payments = Payment.objects.filter(loan_id=loan_id,
                                      payment_status__lt=PaymentStatusCodes.PAID_ON_TIME,
                                      is_restructured=False).select_related('loan',
                                                                            'payment_status', 'account_payment').order_by('payment_number')
    grab_payment_data_list = []
    for payment in payments.iterator():
        grab_payment_data = GrabPaymentData()
        grab_payment_data.loan_id = payment.loan.id
        grab_payment_data.payment_status_code = payment.payment_status.status_code
        grab_payment_data.payment_number = payment.payment_number
        grab_payment_data.due_date = payment.due_date
        grab_payment_data.ptp_date = payment.ptp_date
        grab_payment_data.ptp_robocall_template_id = (
            payment.ptp_robocall_template.id if payment.ptp_robocall_template else None
        )
        grab_payment_data.is_ptp_robocall_active = payment.is_ptp_robocall_active
        grab_payment_data.due_amount = payment.due_amount
        grab_payment_data.installment_principal = payment.installment_principal
        grab_payment_data.installment_interest = payment.installment_interest
        grab_payment_data.paid_date = payment.paid_date
        grab_payment_data.paid_amount = payment.paid_amount
        grab_payment_data.redeemed_cashback = payment.redeemed_cashback
        grab_payment_data.cashback_earned = payment.cashback_earned
        grab_payment_data.late_fee_amount = payment.late_fee_amount
        grab_payment_data.late_fee_applied = payment.late_fee_applied
        grab_payment_data.discretionary_adjustment = payment.discretionary_adjustment
        grab_payment_data.is_robocall_active = payment.is_robocall_active
        grab_payment_data.is_success_robocall = payment.is_success_robocall
        grab_payment_data.is_collection_called = payment.is_collection_called
        grab_payment_data.uncalled_date = payment.uncalled_date
        grab_payment_data.reminder_call_date = payment.reminder_call_date
        grab_payment_data.is_reminder_called = payment.is_reminder_called
        grab_payment_data.is_whatsapp = payment.is_whatsapp
        grab_payment_data.is_whatsapp_blasted = payment.is_whatsapp_blasted
        grab_payment_data.paid_interest = payment.paid_interest
        grab_payment_data.paid_principal = payment.paid_principal
        grab_payment_data.paid_late_fee = payment.paid_late_fee
        grab_payment_data.ptp_amount = payment.ptp_amount
        grab_payment_data.change_due_date_interest = payment.change_due_date_interest
        grab_payment_data.is_restructured = payment.is_restructured
        grab_payment_data.account_payment_id = (
            payment.account_payment.id if payment.account_payment else None
        )
        grab_payment_data.payment_id = payment.id
        grab_payment_data.description = 'loan_is_halted' if not is_description_flag else 'loan_is_resumed'
        grab_payment_data_list.append(grab_payment_data)
    GrabPaymentData.objects.bulk_create(grab_payment_data_list, batch_size=30)
    logger.info({
        "task": "update_grab_payment_data_for_halt_resume_v2",
        "loan_id": loan_id,
        "is_description_flag": is_description_flag,
        "status": "exiting_process"
    })


@task(name="grab_resume_queue")
def trigger_loan_resume_sub_task_v2(account_id):
    """
        DOCUMENTATION:
        This Task is the subtask for resuming.(called by trigger_grab_loan_resume_v2)
        LOAN is already halted at this stage.


        The flow for the tasks for calling tasks are as follows:
        1. trigger_grab_loan_halt_v2 -- Halt all grab loans.
        2. trigger_grab_loan_resume_v2 -- resumes all loan.
        3. trigger_loan_resume_final_task_v2 -- will be called on the resume date.

        THIS FEATURE IS FOR HALTING AND RESUMING ALL LOANS
    """
    from juloserver.grab.services.loan_halt_resume_services import (
        retro_account_payment_due_date,
        update_loan_payments_for_loan_resume_v2,
        get_loan_halt_and_resume_dates
    )
    logger.info({
        "task": "trigger_loan_resume_sub_task_v2",
        "account_id": account_id,
        "action": "starting_trigger_resume_halt_account"
    })
    account = Account.objects.get_or_none(pk=account_id)
    if not account:
        raise GrabHaltResumeError("Invalid AccountID: {}".format(account_id))
    grab_loan_data_set = GrabLoanData.objects.only(
        'id', 'loan_id', 'account_halt_status', 'account_halt_info'
    )
    prefetch_grab_loan_data = Prefetch('grabloandata_set', to_attr='grab_loan_data_set',
                                       queryset=grab_loan_data_set)
    join_tables = [prefetch_grab_loan_data]
    loans = account.loan_set.prefetch_related(
        *join_tables).select_related('loan_status').filter(
        loan_status_id=LoanStatusCodes.HALT
    )
    with transaction.atomic():
        resume_date = None
        for loan in loans:
            if loan.loan_status_id != LoanStatusCodes.HALT:
                logger.info({
                    "task": "trigger_loan_halt_sub_task_v2",
                    "loan_id": loan.id,
                    "account_id": account_id,
                    "error": "Loan_not_HALTED"
                })
                continue
            logger.info({
                "task": "trigger_loan_halt_sub_task_v2",
                "loan_id": loan.id,
                "account_id": account_id,
                "action": "starting_loan_updation"
            })
            grab_loan_data = loan.grab_loan_data_set[0]
            if not grab_loan_data:
                logger.info({
                    "task": "trigger_loan_halt_sub_task_v2",
                    "loan_id": loan.id,
                    "account_id": account_id,
                    "error": "GRAB_LOAN_DATA_NOT_FOUND"
                })
                continue
            halted_dates = get_loan_halt_and_resume_dates(grab_loan_data)
            resume_date = halted_dates[-1]["account_resume_date"]
            halt_date = halted_dates[-1]["account_halt_date"]
            update_loan_payments_for_loan_resume_v2(loan, resume_date, halt_date)
            grab_loan_data.update_safely(
                account_halt_status=AccountHaltStatus.HALTED_UPDATED_RESUME_LOGIC,
                refresh=False)
            logger.info({
                "task": "trigger_loan_halt_sub_task_v2",
                "loan_id": loan.id,
                "account_id": account_id,
                "action": "ending_loan_updation"
            })
            update_grab_payment_data_for_halt_resume_v2.apply_async(
                (loan.id,), {'is_description_flag': True},
                eta=timezone.localtime(timezone.now()) + timedelta(minutes=10))
        logger.info({
            "task": "trigger_loan_resume_sub_task_v2",
            "action": "updated_all_loan_updation_pending"
        })
        retro_account_payment_due_date(account_id)
        logger.info({
            "task": "trigger_loan_resume_sub_task_v2",
            "action": "updated_account_payments"
        })
        application = Application.objects.only('id').filter(
            account_id=account_id,
            application_status_id=ApplicationStatusCodes.LOC_APPROVED
        ).last()
        if application:
            ApplicationNote.objects.create(
                application_id=application.id,
                note_text='Account has been Updated to Resume. Resume-date: ({})'.format(resume_date)
            )
    logger.info({
        "task": "trigger_loan_halt_sub_task_v2",
        "account_id": account_id,
        "action": "ending_trigger_loan_halt_account"
    })


@task(queue='grab_resume_queue')
def trigger_loan_resume_final_task_v2():
    """
        DOCUMENTATION:
        This task needs to be called after loan is resumed on date of resume.

        The flow for the tasks for calling tasks are as follows:
        1. trigger_grab_loan_halt_v2 -- Halt all grab loans.
        2. trigger_grab_loan_resume_v2 -- resumes all loan.
        3. trigger_loan_resume_final_task_v2 -- will be called on the resume date.

        THIS FEATURE IS FOR HALTING AND RESUMING ALL LOANS
    """
    logger.info({
        "task": "trigger_loan_resume_final_task_v2",
        "action": "starting_process"
    })
    grab_loan_datas = GrabLoanData.objects.filter(
        account_halt_status=AccountHaltStatus.HALTED_UPDATED_RESUME_LOGIC,
        loan__loan_status_id=LoanStatusCodes.HALT
    ).only('id')
    logger.info({
        "task": "trigger_loan_resume_final_task_v2",
        "action": "fetched_grab_loan_datas"
    })
    for grab_loan_data in grab_loan_datas.iterator():
        with transaction.atomic():
            trigger_loan_resume_final_task_v2_subtask.delay(grab_loan_data.id)
    logger.info({
        "task": "trigger_loan_resume_final_task_v2",
        "action": "ending_process"
    })


@task(queue='grab_resume_queue')
def trigger_loan_resume_final_task_v2_subtask(grab_loan_data_id):
    """
        DOCUMENTATION:
        This task needs to be called by trigger_loan_resume_final_task_v2
        for updating the loan status
    """
    from juloserver.grab.services.services import update_loan_status_for_halted_or_resumed_loan
    grab_loan_data = GrabLoanData.objects.select_related('loan').get(pk=grab_loan_data_id)
    loan = grab_loan_data.loan
    update_loan_status_for_halted_or_resumed_loan(loan)
    grab_loan_data.update_safely(
        account_halt_status=AccountHaltStatus.RESUMED, refresh=False)


@task(queue='grab_global_queue')
def trigger_180_dpd_trigger_for_loan_sync():
    logger.info({
        "task": "trigger_180_dpd_trigger_for_loan_sync",
        "status": "started processing data"
    })
    processing_batch_size = 1000

    oldest_unpaid_payments_queryset = Payment.objects.only('id', 'loan_id', 'due_date', 'payment_status_id') \
        .not_paid_active().order_by('due_date')
    prefetch_oldest_unpaid_payments = Prefetch('payment_set', to_attr="grab_oldest_unpaid_payments",
                                               queryset=oldest_unpaid_payments_queryset)

    grab_loan_data_set = GrabLoanData.objects.only(
        'id', 'loan_id', 'account_halt_status', 'account_halt_info'
    )
    prefetch_grab_loan_data = Prefetch('grabloandata_set', to_attr='grab_loan_data_set',
                                       queryset=grab_loan_data_set)

    prefetch_join_tables = [
        prefetch_oldest_unpaid_payments,
        prefetch_grab_loan_data
    ]
    loans = Loan.objects.prefetch_related(*prefetch_join_tables).filter(
        account__account_lookup__workflow__name=WorkflowConst.GRAB,
        loan_status_id=LoanStatusCodes.LOAN_180DPD,
    ).order_by('id')
    loan_ids = loans.values_list('id', flat=True)
    loans_count = len(loan_ids)
    starting_index = 0
    logger.info({
        "task": "trigger_180_dpd_trigger_for_loan_sync",
        "status": "queried and batched successfully",
        "loan_count": loans_count,
        "batching_size": processing_batch_size
    })
    for i in list(range(0, loans_count, processing_batch_size)):
        batched_loans = loans.filter(
            id__in=loan_ids[
                   starting_index:starting_index + processing_batch_size]
        )
        starting_index = starting_index + processing_batch_size
        for loan in batched_loans:
            dpd = 0
            if len(loan.grab_oldest_unpaid_payments) > 0:
                dpd = loan.grab_oldest_unpaid_payments[0].get_grab_dpd
            if dpd == GrabWriteOffStatus.GRAB_180_DPD_CUT_OFF:
                trigger_grab_loan_sync_api_async_task.delay(loan.id)
    logger.info({
        "task": "trigger_180_dpd_trigger_for_loan_sync",
        "status": "successfully triggered for all batches"
    })


@task(queue='grab_halt_queue')
def task_update_account_halt_info_format(loan_id):
    grab_loan_data = GrabLoanData.objects.filter(
        loan_id=loan_id,
        account_halt_info__isnull=False
    ).last()
    if grab_loan_data:
        account_halt_info = grab_loan_data.account_halt_info
        if isinstance(account_halt_info, str):
            account_halt_info = json.loads(account_halt_info)
            grab_loan_data.account_halt_info = account_halt_info
            grab_loan_data.save(update_fields=['udate', 'account_halt_info'])


@task(queue='grab_halt_queue')
def update_payment_status_grab():
    """
        Goes through every unpaid payment for loan active and by comparing its due date and
        today's date, update its status (along with its loan status)
        Also need to incorporate GRAB halting for this calculation.

        NEED to release
        - https://juloprojects.atlassian.net/browse/GRABSUB-20
        before implementing this.
    """
    from juloserver.julo.tasks import update_payment_status_subtask

    logger.info({
        "task_name": "update_payment_status_grab",
        "action": "starting the grab payment status task"
    })

    raw_sql_query = """
        SELECT x.doc ->> 'account_halt_date' AS account_halt_date,
        x.doc ->> 'account_resume_date' AS account_resume_date,
        gld.loan_id as loan_id,
        date(x.doc ->> 'account_resume_date') - date(x.doc ->> 'account_halt_date') as diff
        FROM ops.grab_loan_data gld join ops.loan l on l.loan_id = gld.loan_id
        CROSS JOIN LATERAL jsonb_array_elements(gld.account_halt_info) AS x(doc)
        where l.loan_status_code >= 220 and l.loan_status_code < 241;
    """
    grab_payment_processing_dict = dict()
    with connection.cursor() as cursor:
        cursor.execute(raw_sql_query)
        data = cursor.fetchall()

    logger.info({
        "task_name": "update_payment_status_grab",
        "action": "successfully run custom query"
    })

    grab_payment_processing_dict_keys = set()
    for halt_date, resume_date, loan_id, gap in data:
        if loan_id not in grab_payment_processing_dict_keys:
            grab_payment_processing_dict[loan_id] = dict()
            grab_payment_processing_dict_keys.add(loan_id)
        grab_payment_processing_dict[loan_id][resume_date] = gap

    # To be called for halted loans
    total_loans = len(list(grab_payment_processing_dict.keys()))
    batch_size = 100
    number_of_batches = (total_loans // batch_size) + 1
    grab_payment_processing_list = list(grab_payment_processing_dict_keys)

    logger.info({
        "task_name": "update_payment_status_grab",
        "action": "processing batching data",
        "number_of_batches": number_of_batches,
        "total_loans": total_loans
    })
    for counter in list(range(number_of_batches)):
        query = Q()
        if not grab_payment_processing_list[counter * batch_size: (counter + 1) * batch_size]:
            continue
        for loan_id in grab_payment_processing_list[counter * batch_size: (counter + 1) * batch_size]:
            subquery = (Q(loan_id=loan_id) & ~Q(
                loan__loan_status__in={
                    LoanStatusCodes.SELL_OFF,
                    LoanStatusCodes.CANCELLED_BY_CUSTOMER,
                    LoanStatusCodes.HALT
                }))
            account_resume_dates = list(grab_payment_processing_dict[loan_id].keys())
            account_halt_gap_days = [grab_payment_processing_dict[loan_id][i] for i in account_resume_dates]
            q_query = Payment.objects.status_tobe_update_grab(
                account_halt_gap_days, account_resume_dates, is_q_query=True)
            query = query | (subquery & q_query)
        unpaid_payments = Payment.objects.not_paid_active().filter(query).only('id')
        for unpaid_payment_id in unpaid_payments.values_list("id", flat=True):
            logger.info({"payment": unpaid_payment_id, "action": "updating_status_from_grab_function"})
            update_payment_status_subtask.delay(unpaid_payment_id)

    logger.info({
        "task_name": "update_payment_status_grab",
        "action": "processed halted payment update",
    })

    # To be called for Non halted Loans
    non_halted_loan_ids = GrabLoanData.objects.filter(
        Q(account_halt_info__isnull=True) | Q(account_halt_info__exact=[])).filter(
        loan_id__isnull=False).exclude(
        loan__loan_status__in={
            LoanStatusCodes.SELL_OFF,
            LoanStatusCodes.CANCELLED_BY_CUSTOMER,
            LoanStatusCodes.HALT,
            LoanStatusCodes.LENDER_REJECT,
            LoanStatusCodes.PAID_OFF,
            LoanStatusCodes.SPHP_EXPIRED,
            LoanStatusCodes.GRAB_AUTH_FAILED,
            LoanStatusCodes.LOAN_INVALIDATED
        }).values_list('loan_id', flat=True)

    non_halted_payment_ids = Payment.objects.status_tobe_update_grab().not_paid_active().filter(
        loan_id__in=non_halted_loan_ids).exclude(loan__loan_status__in={
            LoanStatusCodes.SELL_OFF,
            LoanStatusCodes.CANCELLED_BY_CUSTOMER,
            LoanStatusCodes.HALT,
            LoanStatusCodes.LENDER_REJECT,
            LoanStatusCodes.PAID_OFF,
            LoanStatusCodes.SPHP_EXPIRED,
            LoanStatusCodes.GRAB_AUTH_FAILED,
            LoanStatusCodes.LOAN_INVALIDATED
        }).only('id').values_list("id", flat=True)

    for non_halted_payment_id in non_halted_payment_ids:
        logger.info({
            "payment": non_halted_payment_id,
            "action": "updating_status_from_grab_function for non halted loan"})
        update_payment_status_subtask.delay(non_halted_payment_id)

    logger.info({
        "task_name": "update_payment_status_grab",
        "action": "processed non halted payment update",
    })


@task(queue='grab_halt_queue')
def generate_move_auth_info_cards():
    from juloserver.streamlined_communication.constant import CardProperty
    from juloserver.grab.utils import ImageNames, create_image

    M_BUTTON = 'M.BUTTON'

    data_to_be_loaded = [
        {
            'status': LoanStatusCodes.INACTIVE,
            'additional_condition': CardProperty.GRAB_INFO_CARD_AUTH_SUCCESS,
            'title': 'Lanjutkan Transaksi Anda',
            'content': 'Lanjutkan tanda tangan digital sekarang sebelum pengajuanmu kadaluarsa.',
            'button': ['Tanda tangan SPHP'],
            'button_name': [M_BUTTON],
            'click_to': ['/agreement_summary'],
            'template_type': '2',
            'card_number': 1,
            'text_colour': '#ffffff',
            'title_colour': '#ffffff',
            'background_url': ImageNames.DESIGNS_REAL,
            'additional_images': [],
            'button_url': ['nil'],
        },
        {
            'status': LoanStatusCodes.INACTIVE,
            'additional_condition': CardProperty.GRAB_INFO_CARD_AUTH_PENDING,
            'title': 'Dalam proses verifikasi ⏳',
            'content': 'Data pengajuan Anda telah diterima dan sedang diverifikasi. '
            'Silahkan kembali dalam satu hari kerja untuk memeriksa status pengajuan Anda.',
            'button': [],
            'button_name': [],
            'click_to': [],
            'template_type': '2',
            'card_number': 1,
            'text_colour': '#ffffff',
            'title_colour': '#ffffff',
            'background_url': ImageNames.DESIGNS_REAL,
            'additional_images': [],
            'button_url': ['nil'],
        },
        {
            'status': LoanStatusCodes.LENDER_REJECT,
            'additional_condition': CardProperty.GRAB_INFO_CARD_AUTH_FAILED,
            'title': 'Mohon maaf 🙏',
            'content': 'Permohonan Anda belum dapat disetujui untuk saat ini karena belum memenuhi kriteria yang ada.',
            'button_name': [],
            'button': [],
            'click_to': [],
            'template_type': '2',
            'card_number': 1,
            'text_colour': '#ffffff',
            'title_colour': '#ffffff',
            'background_url': ImageNames.DESIGNS_REAL,
            'additional_images': [],
            'button_url': [],
        },
        {
            'status': LoanStatusCodes.LENDER_REJECT,
            'additional_condition': CardProperty.GRAB_INFO_CARD_AUTH_FAILED_4002,
            'title': 'Pengajuan Kamu Gagal',
            'content': 'Pastikan nomor HP yang kamu gunakan di GrabModal dan aplikasi driver sama. '
            'Kamu bisa ubah nomor HP GrabModal kamu lewat halaman Profil, ya.',
            'button_name': [],
            'button': [],
            'click_to': [],
            'template_type': '2',
            'card_number': 1,
            'text_colour': '#ffffff',
            'title_colour': '#ffffff',
            'background_url': ImageNames.DESIGNS_REAL,
            'additional_images': [],
            'button_url': [],
        },
    ]
    for data in data_to_be_loaded:
        button_2_properties = {
            'card_type': '2',
            'title': data['title'],
            'title_color': data['title_colour'],
            'text_color': data['text_colour'],
            'card_order_number': data['card_number'],
        }

        info_card = InfoCardProperty.objects.create(**button_2_properties)
        button_info_card = dict()
        if data['button']:
            for idx, image_url in enumerate(data['button']):
                button_info_card['info_card_property'] = info_card
                button_info_card['text'] = data['button'][idx]
                button_info_card['button_name'] = data['button_name'][idx]
                button_info_card['action_type'] = CardProperty.WEBPAGE
                button_info_card['destination'] = data['click_to'][idx]
                button_info_card['text_color'] = data['text_colour']
                button, _ = InfoCardButtonProperty.objects.get_or_create(**button_info_card)

        data_streamlined_message = {
            'message_content': data['content'],
            'info_card_property': info_card,
        }
        message = StreamlinedMessage.objects.create(**data_streamlined_message)
        status = StatusLookup.objects.filter(status_code=data['status']).last()
        data_for_streamlined_comms = {
            'status_code': status,
            'status': data['status'],
            'communication_platform': CommunicationPlatform.INFO_CARD,
            'message': message,
            'description': 'retroloaded grab card move auth information',
            'is_active': True,
            'extra_conditions': data['additional_condition'],
        }
        streamlined_communication = StreamlinedCommunication.objects.create(
            **data_for_streamlined_comms
        )
        # create image for background
        if data['background_url']:
            create_image(
                info_card.id, CardProperty.IMAGE_TYPE.card_background_image, data['background_url']
            )

        if data['additional_images']:
            additional_image_url = data['additional_images']
            additional_image_url = additional_image_url[0]
            create_image(
                info_card.id, CardProperty.IMAGE_TYPE.card_optional_image, str(additional_image_url)
            )


@task(queue="grab_global_queue")
def trigger_auth_call_for_loan_creation(loan_id, retry_attempt=0):
    from juloserver.loan.services.loan_related import update_loan_status_and_loan_history
    from juloserver.grab.services.loan_related import (
        get_change_reason_and_loan_status_change_mapping_grab,
    )
    from juloserver.grab.services.services import validate_grab_application_auth

    logger.info(
        {
            "task": "trigger_auth_call_for_loan_creation",
            "status": "starting auth_call task",
            "loan_id": loan_id,
            "retry_attempt": retry_attempt,
        }
    )
    error_code = None
    error_message = None
    MAX_AUTH_RETRY_LIMIT = 6
    loan = Loan.objects.select_related('customer').filter(id=loan_id).last()
    if not loan:
        return
    customer = loan.customer
    application_190 = customer.application_set.filter(
        application_status_id=ApplicationStatusCodes.LOC_APPROVED, workflow__name=WorkflowConst.GRAB
    ).last()
    if not application_190:
        raise GrabLogicException("GRAB APPLICATION 190 NOT FOUND. LOAN_ID: {}".format(loan.id))
    validate_grab_application_auth(application_190, loan, retry_attempt)

    is_reached_180_before = is_application_reached_180_before(application=application_190)

    next_retry_delay = timedelta(minutes=pow(2, retry_attempt))
    grab_loan_data = GrabLoanData.objects.get_or_none(loan=loan)
    txn_id = grab_loan_data.auth_transaction_id if grab_loan_data else None
    logger.info(
        {
            "task": "trigger_auth_call_for_loan_creation",
            "status": "Triggering Auth Call",
            "loan_id": loan_id,
            "retry_attempt": retry_attempt,
        }
    )
    response = GrabClient.submit_loan_creation(
        loan_id=loan.id, customer_id=loan.customer.id, txn_id=txn_id
    )
    if not isinstance(response, requests.Response):
        if retry_attempt > MAX_AUTH_RETRY_LIMIT:
            update_loan_status_and_loan_history(
                loan_id=loan.id,
                new_status_code=LoanStatusCodes.LENDER_REJECT,
                change_reason=GRAB_AUTH_FAILED_3_MAX_CREDS_ERROR_MESSAGE
                if is_reached_180_before
                else "Grab API Error",
            )
            raise GrabLogicException("No response from Grab Server for AuthAPI")
        trigger_auth_call_for_loan_creation.apply_async(
            (loan_id, retry_attempt + 1), eta=timezone.localtime(timezone.now() + next_retry_delay)
        )
        return
    if isinstance(response, requests.Response) and response.status_code not in {
        status.HTTP_200_OK,
        status.HTTP_201_CREATED,
    }:
        response_content = json.loads(response.content)
        if 'error' in response_content:
            if 'code' in response_content['error']:
                error_code = response_content['error']['code']
            if 'message' in response_content['error']:
                error_message = response_content['error']['message']
    customer = loan.customer
    application_id = loan.application_id2
    if response.status_code not in {status.HTTP_200_OK, status.HTTP_201_CREATED}:
        logger.info({
            "task": "trigger_auth_call_for_loan_creation",
            "status": "Request failed (response not in 200/201)",
            "loan_id": loan_id,
            "retry_attempt": retry_attempt,
            "status_code": response.status_code
        })
        crs_failed_validation_service = CRSFailedValidationService()
        if isinstance(error_code, int) or isinstance(error_code, str):
            status_to_be_changed, change_reason = (
                get_change_reason_and_loan_status_change_mapping_grab(int(error_code)))
            if is_reached_180_before:
                change_reason = GRAB_AUTH_FAILED_3_MAX_CREDS_ERROR_MESSAGE

            if int(error_code) in {
                GrabAuthAPIErrorCodes.ERROR_CODE_5001,
                GrabAuthAPIErrorCodes.ERROR_CODE_5002,
                GrabAuthAPIErrorCodes.ERROR_CODE_8002
            }:
                # Will handle All other error codes with 500 response:
                if retry_attempt > MAX_AUTH_RETRY_LIMIT:
                    send_grab_api_timeout_alert_slack.delay(
                        customer_id=customer.id if customer else None,
                        response=response,
                        uri_path=response.request.url,
                        phone_number=customer.phone if customer else None,
                        application_id=application_id if application_id else None,
                        loan_id=loan.id,
                    )
                    logger.info({
                        "task": "trigger_auth_call_for_loan_creation",
                        "status": "Request failed (response not in 200/201)",
                        "loan_id": loan_id,
                        "retry_attempt": retry_attempt,
                        "status_code": response.status_code,
                        "note": "status_change_due_to exhausted_retry"
                    })
                    update_loan_status_and_loan_history(
                        loan_id=loan.id,
                        new_status_code=status_to_be_changed,
                        change_reason=change_reason,
                    )
                    logger.info(
                        {
                            "task": "trigger_auth_call_for_loan_creation",
                            "status": "ending auth_call task",
                            "loan_id": loan_id,
                            "retry_attempt": retry_attempt,
                        }
                    )
                    return
                logger.info(
                    {
                        "task": "trigger_auth_call_for_loan_creation",
                        "status": "retry triggered for 5001/5002",
                        "loan_id": loan_id,
                        "retry_attempt": retry_attempt,
                        "status_code": response.status_code,
                    }
                )
                trigger_auth_call_for_loan_creation.apply_async(
                    (loan_id, retry_attempt + 1),
                    eta=timezone.localtime(timezone.now() + next_retry_delay),
                )
                return
            elif int(error_code) in {
                GrabAuthAPIErrorCodes.ERROR_CODE_4001,
                GrabAuthAPIErrorCodes.ERROR_CODE_4002,
                GrabAuthAPIErrorCodes.ERROR_CODE_4006,
                GrabAuthAPIErrorCodes.ERROR_CODE_4008,
                GrabAuthAPIErrorCodes.ERROR_CODE_4011,
                GrabAuthAPIErrorCodes.ERROR_CODE_4014,
                GrabAuthAPIErrorCodes.ERROR_CODE_4015,
                GrabAuthAPIErrorCodes.ERROR_CODE_4025,
            }:
                if int(error_code) == GrabAuthAPIErrorCodes.ERROR_CODE_4025:
                    trigger_application_creation_grab_api.apply_async((application_190.id,))
                logger.info(
                    {
                        "task": "trigger_auth_call_for_loan_creation",
                        "status": "loan status change for 400",
                        "loan_id": loan_id,
                        "retry_attempt": retry_attempt,
                        "status_code": response.status_code,
                        "error_code": error_code,
                    }
                )
                update_loan_status_and_loan_history(
                    loan_id=loan.id,
                    new_status_code=status_to_be_changed,
                    change_reason=change_reason,
                )
                logger.info(
                    {
                        "task": "trigger_auth_call_for_loan_creation",
                        "status": "ending auth_call task",
                        "loan_id": loan_id,
                        "retry_attempt": retry_attempt,
                    }
                )
                return
            else:
                logger.info(
                    {
                        "task": "trigger_auth_call_for_loan_creation",
                        "status": "loan status change 400",
                        "loan_id": loan_id,
                        "retry_attempt": retry_attempt,
                        "status_code": response.status_code,
                        "error_code": error_code,
                    }
                )

                if GrabApiLogConstants.FAILED_CRS_VALIDATION_ERROR_RESPONSE in error_message:
                    crs_failed_validation_service.create_or_update_crs_failed_data(loan)

                update_loan_status_and_loan_history(
                    loan_id=loan.id,
                    new_status_code=status_to_be_changed,
                    change_reason=change_reason,
                )
                return
        elif response.status_code >= status.HTTP_500_INTERNAL_SERVER_ERROR:
            if retry_attempt > MAX_AUTH_RETRY_LIMIT:
                send_grab_api_timeout_alert_slack.delay(
                    customer_id=customer.id if customer else None,
                    response=response,
                    uri_path=response.request.url,
                    phone_number=customer.phone if customer else None,
                    application_id=application_id if application_id else None,
                    loan_id=loan.id,
                )
                logger.info(
                    {
                        "task": "trigger_auth_call_for_loan_creation",
                        "status": "Request failed (response not in 200/201)",
                        "loan_id": loan_id,
                        "retry_attempt": retry_attempt,
                        "status_code": response.status_code,
                        "note": "status_change_due_to exhausted_retry (5xx)",
                    }
                )
                update_loan_status_and_loan_history(
                    loan_id=loan.id,
                    new_status_code=LoanStatusCodes.LENDER_REJECT,
                    change_reason=GRAB_AUTH_FAILED_3_MAX_CREDS_ERROR_MESSAGE if
                                  is_reached_180_before else "Grab API Failure",
                )
                return
            trigger_auth_call_for_loan_creation.apply_async(
                (loan_id, retry_attempt + 1),
                eta=timezone.localtime(timezone.now() + next_retry_delay),
            )
            return
        elif (
            status.HTTP_400_BAD_REQUEST
            <= response.status_code
            < status.HTTP_500_INTERNAL_SERVER_ERROR
        ):
            if GrabApiLogConstants.FAILED_CRS_VALIDATION_ERROR_RESPONSE in error_message:
                crs_failed_validation_service.create_or_update_crs_failed_data(loan)

            update_loan_status_and_loan_history(
                loan_id=loan.id,
                new_status_code=LoanStatusCodes.LENDER_REJECT,
                change_reason=GRAB_AUTH_FAILED_3_MAX_CREDS_ERROR_MESSAGE
                if is_reached_180_before
                else "Grab API Failure",
            )
            return
    else:
        logger.info(
            {
                "task": "trigger_auth_call_for_loan_creation",
                "status": "Triggering PN",
                "loan_id": loan_id,
                "retry_attempt": retry_attempt,
            }
        )
        trigger_push_notification_grab.apply_async(kwargs={'loan_id': loan.id})
        if is_reached_180_before:
            send_sms_to_dax_pass_3_max_creditors(application_190.mobile_phone_1, application_190)
    logger.info(
        {
            "task": "trigger_auth_call_for_loan_creation",
            "status": "ending auth_call task",
            "loan_id": loan_id,
            "retry_attempt": retry_attempt,
        }
    )


@task(queue="grab_global_queue")
def clear_grab_loan_offer_data():
    logger.info({
        "action": "clear_grab_loan_offer_data",
        "message": "starting"
    })

    older_than_days = 30
    today = datetime.today()
    one_month_ago = today - timedelta(days=older_than_days)
    one_month_ago = one_month_ago.replace(hour=0, minute=0, second=0, microsecond=0)

    result = GrabLoanOffer.objects.filter(cdate__lt=one_month_ago).delete()
    logger.info({
        "action": "clear_grab_loan_offer_data",
        "message": "finish, {} deleted".format(result[0])
    })
    return result[0]


@task(queue='grab_global_queue')
def trigger_name_bank_validation_grab(
    validation_id, name_in_bank, bank_name, account_number, mobile_phone, application_id
):
    from juloserver.disbursement.services import trigger_name_in_bank_validation

    """
    Trigger Bank validation:
    data needed for this is:
    1. validation_id: New Name bank validation id
    2. name_in_bank: Customer name in bank
    3. bank_name: Customer bank name
    4. account_number: Customer bank account number
    5. mobile_phone: customer phone number
    6. application_id: Customer application - 190
    """
    logger.info({
        "task": "trigger_name_bank_validation_grab",
        "status": "starting_task",
        "validation_id": validation_id,
        "application_id": application_id
    })
    application = Application.objects.get_or_none(id=application_id)
    if not application:
        raise GrabLogicException("Application missing for bank account validation")
    data_to_validate = dict()
    data_to_validate['name_bank_validation_id'] = validation_id
    data_to_validate['name_in_bank'] = name_in_bank
    data_to_validate['bank_name'] = bank_name
    data_to_validate['account_number'] = account_number
    data_to_validate['mobile_phone'] = mobile_phone
    data_to_validate['application'] = application
    # this will not create new entry of name bank validation because we provide the
    # name_bank_validation_id
    validation = trigger_name_in_bank_validation(data_to_validate, new_log=True)
    validation.validate()
    logger.info({
        "task": "trigger_name_bank_validation_grab",
        "status": "ending_task",
        "validation_id": validation_id,
        "application_id": application_id
    })


@task(queue='grab_resume_queue')
def task_update_payment_status_to_paid_off():
    logger.info({
        "task": "task_update_payment_status_to_paid_off",
        "action": "started processing"
    })
    data = GrabSqlUtility.run_sql_query_for_paid_off_payment_invalid_status(
        GRAB_ACCOUNT_LOOKUP_NAME)
    loan_ids_set = set()
    for (loan_id,) in data:
        if loan_id not in loan_ids_set:
            update_status_for_paid_off_payment_grab.delay(loan_id)
        loan_ids_set.add(loan_id)
    logger.info({
        "task": "task_update_payment_status_to_paid_off",
        "action": "ending task"
    })


@task(queue='grab_resume_queue')
def update_status_for_paid_off_payment_grab(loan_id):
    from juloserver.loan.services.loan_related import update_loan_status_and_loan_history
    from juloserver.account_payment.services.payment_flow import update_payment_paid_off_status
    logger.info({
        "task": "update_status_for_paid_off_payment_grab",
        "loan_id": loan_id,
        "action": "starting processing"
    })
    unpaid_payment_qs = Payment.objects.not_paid_active()
    prefetch_unpaid_payment = Prefetch("payment_set", unpaid_payment_qs, to_attr="prefetch_unpaid_payment")
    join_tables = [prefetch_unpaid_payment]
    loan = Loan.objects.prefetch_related(*join_tables).select_related('loan_status').filter(
        id=loan_id,
        loan_status_id__in={
            LoanStatusCodes.CURRENT, LoanStatusCodes.LOAN_1DPD,
            LoanStatusCodes.LOAN_5DPD, LoanStatusCodes.LOAN_30DPD,
            LoanStatusCodes.LOAN_60DPD, LoanStatusCodes.LOAN_90DPD,
            LoanStatusCodes.LOAN_120DPD, LoanStatusCodes.LOAN_150DPD,
            LoanStatusCodes.LOAN_180DPD
        }
    ).last()
    if not loan:
        return
    total_due_amount = 0
    for payment in loan.prefetch_unpaid_payment:
        if payment.due_amount == 0 and payment.status not in {
            PaymentStatusCodes.PAID_ON_TIME,
            PaymentStatusCodes.PAID_LATE,
            PaymentStatusCodes.PAID_WITHIN_GRACE_PERIOD
        }:
            update_payment_paid_off_status(payment)
            payment.save(update_fields=['payment_status'])
        total_due_amount += payment.due_amount
    if total_due_amount == 0 and loan.status != LoanStatusCodes.PAID_OFF:
        update_loan_status_and_loan_history(
            loan_id=loan.id,
            new_status_code=LoanStatusCodes.PAID_OFF,
            change_by_id=None,
            change_reason="Loan paid off(UPDATE MANUAL)")
        if loan.product.has_cashback:
            make_cashback_available(loan)
        return
    current_loan_status = loan.status
    loan.update_status()
    if current_loan_status != loan.status:
        update_loan_status_and_loan_history(
            loan_id=loan.id,
            new_status_code=loan.status,
            change_by_id=None,
            change_reason="update loan status after payment paid off(CRON UPDATE)")

    logger.info({
        "task": "update_status_for_paid_off_payment_grab",
        "loan_id": loan_id,
        "action": "ending process"
    })


@task(queue="grab_global_queue")
def send_sms_to_user_at_100_and_will_expire_in_1_day():
    from juloserver.moengage.utils import chunks
    applications_details = Application.objects.select_related('workflow').filter(
        application_status_id=ApplicationStatusCodes.FORM_CREATED,
        workflow__name=WorkflowConst.GRAB
    ).values_list('id', 'cdate', 'application_status_id', 'mobile_phone_1')

    for chunked_applications_details in chunks(applications_details, 10):
        send_sms_to_user_at_100_and_will_expire_in_1_day_sub_task1.delay(chunked_applications_details)


@task(queue="grab_global_queue")
def send_sms_to_user_at_100_and_will_expire_in_1_day_sub_task1(chunked_applications_details):
    for application_id, created_date, application_status_id, mobile_phone_1 in chunked_applications_details:
        if not mobile_phone_1:
            continue

        send_sms_to_user_at_100_and_will_expire_in_1_day_sub_task2(
            application_id, created_date, application_status_id
        )


def get_application_history_data(application_id, application_status_id):
    application_history = (
        ApplicationHistory.objects.filter(
            application_id=application_id, status_new=application_status_id
        )
        .last()
    )
    if application_history is None:
        return

    return application_history


def get_application_sms_history_count_based_on_template_code(application_id, template_code):
    yesterday = timezone.localtime(timezone.now()) - timedelta(days=1)
    sms_count = (
        SmsHistory.objects.filter(application_id=application_id, cdate__gt=yesterday,
                                  template_code=template_code).count()
    )
    return sms_count


def send_grab_sms_based_on_template_code(template_code, application):
    try:
        julo_sms_client = get_julo_sms_client()
        julo_sms_client.send_grab_sms_based_on_template_code(
            template_code, application
        )
    except Exception as e:
        logger.error({
            "action": "send_grab_sms_based_on_template_code",
            "template_code": template_code,
            "application": application.id,
            'error': str(e)
        })
        pass


def send_sms_to_user_at_100_and_will_expire_in_1_day_sub_task2(
        application_id: int,
        created_date: datetime,
        application_status_id: int
) -> list:
    application_history = get_application_history_data(application_id, application_status_id)
    if not application_history:
        return

    template_code = GrabSMSTemplateCodes.GRAB_SMS_APP_100_EXPIRE_IN_ONE_DAY
    sms_count = get_application_sms_history_count_based_on_template_code(application_id, template_code)
    if sms_count >= 1:
        return

    six_days_ago = timezone.localtime(timezone.now() - relativedelta(days=6))
    seven_days_ago = timezone.localtime(timezone.now() - relativedelta(days=7))
    # SMS should be sent if the 100 app status still be on 6 days
    if (created_date > seven_days_ago and created_date <= six_days_ago):
        send_grab_sms_based_on_template_code(template_code, application_history.application)


@task(queue="grab_global_queue")
def send_sms_to_user_at_131_for_24_hour():
    from juloserver.moengage.utils import chunks
    applications_details = Application.objects.select_related('workflow').filter(
        application_status_id=ApplicationStatusCodes.APPLICATION_RESUBMISSION_REQUESTED,
        workflow__name=WorkflowConst.GRAB
    ).values_list('id', 'application_status_id', 'mobile_phone_1')
    for chunked_applications_details in chunks(applications_details, 10):
        send_sms_to_user_at_131_for_24_hour_sub_task1.delay(chunked_applications_details)


@task(queue="grab_global_queue")
def send_sms_to_user_at_131_for_24_hour_sub_task1(chunked_applications_details):
    for application_id, application_status_id, mobile_phone_1 in chunked_applications_details:
        if not mobile_phone_1:
            continue

        send_sms_to_user_at_131_for_24_hour_sub_task2(
            application_id, application_status_id
        )


def send_sms_to_user_at_131_for_24_hour_sub_task2(
        application_id: int,
        application_status_id: int,
) -> list:
    application_history = get_application_history_data(application_id, application_status_id)
    if not application_history:
        return

    template_code = GrabSMSTemplateCodes.GRAB_SMS_APP_AT_131_FOR_24_HOUR
    sms_count = get_application_sms_history_count_based_on_template_code(application_id, template_code)
    if sms_count >= 1:
        return

    now = timezone.localtime(timezone.now())
    application_history_cdate = timezone.localtime(application_history.cdate) + timedelta(hours=24)
    if (application_history_cdate.date() == now.date()
            and now.hour == application_history_cdate.hour):
        send_grab_sms_based_on_template_code(template_code, application_history.application)


@task(queue="grab_global_queue")
def trigger_sms_to_submit_digisign(loan_id):
    loan = Loan.objects.select_related('customer').filter(id=loan_id).last()
    if not loan:
        return

    if loan.application_id2:
        application_id = loan.application_id2
    else:
        application_id = loan.application_id

    application_190 = Application.objects.filter(
        application_status_id=ApplicationStatusCodes.LOC_APPROVED,
        workflow__name=WorkflowConst.GRAB,
        id=application_id
    ).last()
    if not application_190 or loan.loan_status.status_code != LoanStatusCodes.INACTIVE:
        return

    is_app_at_180_before = is_application_reached_180_before(application_190)
    if is_app_at_180_before:
        return

    template_code = GrabSMSTemplateCodes.GRAB_SMS_FOR_PROVIDE_DEGISIGN
    send_grab_sms_based_on_template_code(template_code, application_190)


@task(queue='grab_halt_queue')
def mark_sphp_expired_grab():
    """
    Goes through every application in which offers have been made. If
    any of the offers has expired, update the application status.
    """
    logger.info({
        "task": "mark_sphp_expired_grab",
        "action": "started_triggering"
    })
    batch_size = 10
    loan_ids_list = Loan.objects.filter(
        loan_status__in=LoanStatusCodes.inactive_status(),
        sphp_exp_date__isnull=False,
        account__account_lookup__workflow__name=WorkflowConst.GRAB).values_list(
        'id', flat=True)

    for loan_ids in [loan_ids_list[idx:idx + batch_size]
                     for idx in range(0, len(loan_ids_list), batch_size)]:
        mark_sphp_expired_grab_subtask.delay(loan_ids)

    logger.info({
        "task": "mark_sphp_expired_grab",
        "action": "ending task"
    })


@task(queue='grab_halt_queue')
def mark_sphp_expired_grab_subtask(loan_ids):
    from juloserver.loan.services.loan_related import update_loan_status_and_loan_history
    """sub task to run 1app/1worker"""

    loans = Loan.objects.filter(
        id__in=loan_ids)

    for loan in loans.iterator():
        if loan.loan_status_id not in LoanStatusCodes.inactive_status():
            continue

        if loan.sphp_expired:
            update_loan_status_and_loan_history(loan_id=loan.id,
                                                new_status_code=LoanStatusCodes.SPHP_EXPIRED,
                                                change_reason="Legal agreement expired")
            logger.info({
                "task": "mark_sphp_expired_grab_subtask",
                "loan": loan.id,
                "status": "sphp_expired"
            })
        else:
            logger.debug({
                "task": "mark_sphp_expired_grab_subtask",
                "loan": loan.id,
                "status": "sphp_not_yet_expired"
            })


@task(queue="grab_global_queue")
def send_email_to_user_at_131_for_24_hour():
    from juloserver.moengage.utils import chunks
    applications_details = Application.objects.select_related('workflow').filter(
        application_status_id=ApplicationStatusCodes.APPLICATION_RESUBMISSION_REQUESTED,
        workflow__name=WorkflowConst.GRAB
    ).values_list('id', 'application_status_id')
    for chunked_applications_details in chunks(applications_details, 10):
        task_send_email_to_user_131_daily_process_chunk.delay(chunked_applications_details)


@task(queue="grab_global_queue")
def task_send_email_to_user_131_daily_process_chunk(chunked_applications_details):
    for application_id, application_status_id in chunked_applications_details:
        task_send_email_to_user_131_daily_subtask(
            application_id, application_status_id
        )


def get_application_email_history_count_based_on_template_code(application_id, template_code):
    yesterday = timezone.localtime(timezone.now()) - timedelta(days=1)
    email_count = (
        EmailHistory.objects.filter(application_id=application_id, cdate__gt=yesterday,
                                    template_code=template_code).count()
    )
    return email_count


def send_grab_email_based_on_template_code(template_code, application, hour=72):
    try:
        julo_email_client = get_julo_email_client()
        to_email = application.email
        if not to_email:
            application.email = application.customer.email

        julo_email_client.send_grab_email_based_on_template_code(template_code, application, hour)
    except Exception as e:
        logger.error(
            {
                "action": "send_grab_email_based_on_template_code",
                "template_code": template_code,
                "application": application.id,
                "hour": hour,
                'error': str(e),
            }
        )
        pass


def task_send_email_to_user_131_daily_subtask(
        application_id: int,
        application_status_id: int,
) -> list:
    application_history = get_application_history_data(application_id, application_status_id)
    if not application_history:
        return

    template_code = GrabEmailTemplateCodes.GRAB_EMAIL_APP_AT_131
    email_count = get_application_email_history_count_based_on_template_code(application_id, template_code)
    if email_count >= 1:
        return

    timezone.localtime(application_history.cdate)
    now = timezone.localtime(timezone.now())
    application_history_cdate = timezone.localtime(application_history.cdate) + timedelta(hours=24)
    if (application_history_cdate.date() == now.date()
            and now.hour == application_history_cdate.hour):
        send_grab_email_based_on_template_code(template_code, application_history.application, 48)


@task(queue="grab_global_queue")
def send_email_to_user_before_3hr_of_app_expire():
    from juloserver.moengage.utils import chunks
    applications_details = Application.objects.select_related('workflow').filter(
        application_status_id=ApplicationStatusCodes.APPLICATION_RESUBMISSION_REQUESTED,
        workflow__name=WorkflowConst.GRAB
    ).values_list('id', 'application_status_id')
    for chunked_applications_details in chunks(applications_details, 10):
        task_send_email_to_user_before_app_expire_process_chunk.delay(chunked_applications_details)


@task(queue="grab_global_queue")
def task_send_email_to_user_before_app_expire_process_chunk(chunked_applications_details):
    for application_id, application_status_id in chunked_applications_details:
        task_send_email_to_user_before_app_expire_subtask(
            application_id, application_status_id
        )


def task_send_email_to_user_before_app_expire_subtask(
        application_id: int,
        application_status_id: int,
) -> list:
    application_history = get_application_history_data(application_id, application_status_id)
    if not application_history:
        return

    template_code = GrabEmailTemplateCodes.GRAB_EMAIL_APP_AT_131
    email_count = get_application_email_history_count_based_on_template_code(application_id, template_code)
    if email_count >= 1:
        return

    now = timezone.localtime(timezone.now())
    """
        application reaches expiry status 136 after 3 days
        so 3hr before expiration means (3*24-3 = 69hr after application creation)
    """
    application_history_cdate = timezone.localtime(application_history.cdate) + timedelta(hours=69)
    if (application_history_cdate.date() == now.date()
            and now.hour == application_history_cdate.hour):
        application_history.application.application_status_id = (ApplicationStatusCodes.
                                                                 APPLICATION_RESUBMISSION_REQUESTED)
        send_grab_email_based_on_template_code(template_code, application_history.application, 3)


@task(queue='grab_global_queue')
def grab_send_reset_pin_sms(customer, phone_number, reset_pin_key):
    if phone_number:
        reset_pin_page_link = settings.RESET_PIN_JULO_ONE_LINK_HOST + reset_pin_key + '/' + '?grab=true'
        logger.info(
            {
                'status': 'grab_reset_pin_page_link_created',
                'phone_number': phone_number,
                'reset_pin_page_link': reset_pin_page_link,
            }
        )
        julo_sms_client = get_julo_sms_client()
        reset_pin_page_link = shorten_url(reset_pin_page_link)
        if not customer.first_name_only:
            first_name = ''
        else:
            first_name = customer.first_name_only

        msg = (
            'Hai, {}. Kamu terima pesan ini karena ada permintaan ubah PIN. '
            'Klik {} untuk ubah PIN, ya! Jika ini bukan kamu, cek keamanan akunmu.'
        ).format(first_name, reset_pin_page_link)
        phone_number = format_e164_indo_phone_number(phone_number)
        message, response = julo_sms_client.send_sms(phone_number, msg)
        response = response['messages'][0]

        if response["status"] != "0":
            logger.exception(
                {
                    "send_status": response["status"],
                    "message_id": response.get("message-id"),
                    "sms_client_method_name": "grab_send_reset_pin_sms",
                    "error_text": response.get("error-text"),
                }
            )

        template_code = 'grab_reset_pin_by_sms'
        sms = create_sms_history(
            response=response,
            customer=customer,
            message_content=msg,
            to_mobile_phone=format_e164_indo_phone_number(phone_number),
            phone_number_type="mobile_phone_1",
            template_code=template_code,
        )
        if sms:
            logger.info(
                {
                    "status": "grab_sms_created",
                    "sms_history_id": sms.id,
                    "message_id": sms.message_id,
                }
            )


def get_customer_ids_fdc_daily_checker(parameters, current_time):
    from juloserver.loan.services.loan_related import (
        get_fdc_loan_active_checking_for_daily_checker
    )
    customer_ids = get_fdc_loan_active_checking_for_daily_checker(
        parameters, current_time
    )
    return customer_ids


def get_grab_customer_ids(customer_ids):
    """
    return 2 list/set
    1. customer ids
    2. blacklisted customer ids
    """
    grab_utils = GrabUtils()
    grab_utils.set_redis_client()

    grab_customer_ids = set()
    grab_blacklisted_customer_ids = set()
    grab_customers = GrabCustomerData.objects.filter(
        customer_id__in=customer_ids).values("customer_id", "customer__fullname")

    for grab_customer in grab_customers.iterator():
        is_blacklist_user = grab_utils.check_fullname_with_DTTOT(
            grab_customer.get('customer__fullname', '')
        )
        customer_id = grab_customer.get("customer_id")
        if not is_blacklist_user:
            grab_customer_ids.add(customer_id)
        else:
            grab_blacklisted_customer_ids.add(customer_id)

    return grab_customer_ids, grab_blacklisted_customer_ids


@task(queue='grab_global_queue')
def move_app_blacklisted_customers(blacklisted_customer_ids):
    from juloserver.julo.services import process_application_status_change
    fn_name = "move_app_blacklisted_customers"
    logger.info({
        "action": fn_name,
        "message": "starting, reject {} blacklisted customers".format(len(blacklisted_customer_ids))
    })

    # doing chunk
    processed = 0
    for chunk_customer_ids in chunks(list(blacklisted_customer_ids), 50):
        for customer in Customer.objects.filter(id__in=chunk_customer_ids).iterator():
            if customer.account:
                application = customer.account.get_active_application()
                process_application_status_change(
                    application,
                    ApplicationStatusCodes.APPLICATION_DENIED,
                    GRAB_BLACKLIST_CUSTOMER
                )
                processed += 1

    logger.info({
        "action": fn_name,
        "message": "done, reject {} app because blacklisted customers".format(processed)
    })


def trigger_fdc_inquiry_for_active_loan_from_platform_daily_checker_task(
    parameters,
    current_time,
    only_grab=False
):
    from juloserver.loan.tasks.lender_related import (
        fdc_inquiry_for_active_loan_from_platform_daily_checker_subtask
    )
    # by default, it will exclude grab
    update_type = FDCUpdateTypes.DAILY_CHECKER
    if only_grab:
        update_type = FDCUpdateTypes.GRAB_DAILY_CHECKER

    customer_ids = get_customer_ids_fdc_daily_checker(parameters, current_time)
    # chunk to avoid bottleneck
    grab_customer_ids = set()
    grab_blacklisted_customer_ids = set()
    for chunked_customer_ids in chunks(customer_ids, 100):
        temp_grab_customer_ids, temp_grab_blacklisted_customer_ids = get_grab_customer_ids(
            chunked_customer_ids
        )
        grab_customer_ids.update(temp_grab_customer_ids)
        grab_blacklisted_customer_ids.update(temp_grab_blacklisted_customer_ids)


    config = parameters['daily_checker_config']
    rps_throttling = config.get('rps_throttling', 3)
    # we set the RPS to lowest (3 RPS)
    delay = math.ceil(1000 / rps_throttling)
    eta_time = timezone.localtime(current_time)
    for customer_id in customer_ids.iterator():
        if customer_id in grab_blacklisted_customer_ids:
            continue

        if only_grab:
            if customer_id not in grab_customer_ids:
                continue
        else:
            if customer_id in grab_customer_ids:
                continue

        eta_time += timedelta(milliseconds=delay)
        fdc_inquiry_for_active_loan_from_platform_daily_checker_subtask.apply_async(
            (
                customer_id,
                parameters,
                update_type
            ),
            eta=eta_time,
            queue="grab_global_queue"
        )

    move_app_blacklisted_customers.delay(
        grab_blacklisted_customer_ids
    )


@task(queue='grab_global_queue')
def grab_fdc_inquiry_for_active_loan_from_platform_daily_checker_task():
    func_name = "grab_fdc_inquiry_for_active_loan_from_platform_daily_checker_task"
    logger_message = {"action": func_name, "message": "start {}".format(func_name)}
    logger.info(logger_message)

    from juloserver.loan.services.loan_related import (
        get_parameters_fs_check_other_active_platforms_using_fdc,
    )
    parameters = get_parameters_fs_check_other_active_platforms_using_fdc(
        feature_name=FeatureNameConst.GRAB_3_MAX_CREDITORS_CHECK
    )
    if not parameters:
        return

    current_time = timezone.now()

    trigger_fdc_inquiry_for_active_loan_from_platform_daily_checker_task(
        parameters,
        current_time,
        only_grab=True
    )
    logger_message.update({"message": "finish {}".format(func_name)})
    logger.info(logger_message)


def register_privy(application_id):
    from juloserver.julo_privyid.services import get_privy_feature
    from juloserver.julo_privyid.tasks import (
        create_new_privy_user
    )

    privy_feature = get_privy_feature()
    if privy_feature:
        reupload_image_type = ['selfie_ops', 'ktp_self_ops']
        reuploaded_images = Image.objects.filter(
            image_source=application_id,
            image_type__in=reupload_image_type,
            image_status__in=[Image.CURRENT, Image.RESUBMISSION_REQ]
        )
        if not reuploaded_images:
            create_new_privy_user.delay(application_id)


@task(queue="grab_global_queue")
def grab_app_stuck_150_handler_subtask(grab_applications, parameters):
    from juloserver.grab.services.loan_related import (
        get_fdc_active_loan_check,
        is_below_allowed_platforms_limit,
        create_fdc_inquiry_and_execute_check_active_loans_for_grab
    )
    from juloserver.julo.services import process_application_status_change

    for application_id, customer_id in grab_applications:
        fdc_active_loan_checking = get_fdc_active_loan_check(customer_id=customer_id)

        fdc_inquiry = grab_fdc.get_fdc_data_without_expired_rules(parameters, application_id)

        if fdc_inquiry:
            is_eligible = is_below_allowed_platforms_limit(
                number_of_allowed_platforms=parameters['number_of_allowed_platforms'],
                fdc_inquiry=fdc_inquiry,
                fdc_active_loan_checking=fdc_active_loan_checking
            )
            if is_eligible:
                # go to 190
                register_privy(application_id=application_id)
                process_application_status_change(
                    application_id,
                    ApplicationStatusCodes.LOC_APPROVED,
                    'Credit limit activated'
                )
            else:
                # got to 180
                process_application_status_change(
                    application_id,
                    ApplicationStatusCodes.FUND_DISBURSAL_SUCCESSFUL,
                    GRAB_MAX_CREDITORS_REACHED_ERROR_MESSAGE.format(3)
                )
        else:
            register_privy(application_id=application_id)
            process_application_status_change(
                application_id,
                ApplicationStatusCodes.LOC_APPROVED,
                'Credit limit activated'
            )


@task(queue="grab_global_queue")
def grab_app_stuck_150_handler_task():
    func_name = "grab_app_stuck_150_handler_task"
    logger_message = {"action": func_name, "message": "start {}".format(func_name)}
    logger.info(logger_message)

    from juloserver.loan.services.loan_related import (
        get_parameters_fs_check_other_active_platforms_using_fdc,
    )
    parameters = get_parameters_fs_check_other_active_platforms_using_fdc(
        feature_name=FeatureNameConst.GRAB_3_MAX_CREDITORS_CHECK
    )

    if not parameters:
        return

    grab_applications = Application.objects.filter(
        application_status=ApplicationStatusCodes.ACTIVATION_CALL_SUCCESS_AND_BANK_VALIDATE_ONGOING,
        workflow__name=WorkflowConst.GRAB
    )[0:100].values_list('id', 'customer_id')

    for chucked_grab_application in chunks(grab_applications, 10):
        grab_app_stuck_150_handler_subtask.delay(chucked_grab_application, parameters)

    n_grab_application = len(grab_applications)

    logger_message.update({
        "message": "finish {}, {} grab app triggered".format(func_name, n_grab_application)
    })
    logger.info(logger_message)

    return n_grab_application


@task(queue="grab_global_queue")
def clear_grab_payment_plans():
    logger.info({
        "action": "clear_grab_payment_plans",
        "message": "starting"
    })

    current_time = timezone.localtime(timezone.now())
    last_24_hours = current_time - timedelta(hours=24)

    result = GrabPaymentPlans.objects.filter(udate__lt=last_24_hours).delete()
    logger.info({
        "action": "clear_grab_payment_plans",
        "message": "finish, {} deleted".format(result[0])
    })
    return result[0]


@task(queue="grab_global_queue")
def sending_sms_async_worker(applications_data, do_validation=False):
    action = "sending_sms_async_worker"
    """
    {
        id: application_id,
        unique_link: string,
        hashed_unique_link: string
    }
    """
    from juloserver.grab.services.services import (
        EmergencyContactService
    )
    service = EmergencyContactService(
        sms_client=get_julo_sms_client()
    )

    for application in applications_data:
        is_ec_received_sms_before = False
        if do_validation:
            is_ec_received_sms_before = service.is_ec_received_sms_before(
                application_id=application.get('id'), hours=24)

        if not is_ec_received_sms_before:
            logger.info({
                "action": action,
                "application_id": application.get('id')
            })
            service.send_sms_to_ec(
                application_id=application.get('id'),
                unique_link=application.get('unique_link'),
                hashed_unique_link=application.get('hashed_unique_link')
            )


@task(queue="grab_global_queue")
def sending_sms_to_emergency_contact_worker(application_ids, parameters):
    from juloserver.grab.services.services import (
        EmergencyContactService,
        get_redis_client
    )

    service = EmergencyContactService(
        redis_client=get_redis_client()
    )

    action = "sending_sms_to_emergency_contact_worker"
    logger.info({
        "action": action,
        "status": "starting: {} data".format(len(application_ids))
    })

    applications = Application.objects.filter(id__in=application_ids).\
        values('id', 'kin_name')

    applications_data = []
    for application in applications.iterator():
        is_ec_received_sms_before = service.is_ec_received_sms_before(application.get('id'))
        unique_link = service.generate_unique_link(
            application_id=application.get('id'),
            application_kin_name=application.get('kin_name')
        )

        # this probaly the user do reapply
        # because the app id is coming from application that reach 124 and store to redis
        if is_ec_received_sms_before:
            service.save_application_id_to_redis(application_id=json.dumps({
                'application_id': application.get('id'),
                'unique_link': unique_link
                }), key=service.reapply_redis_key)
            continue

        expiration_date = service.set_expired_time(parameters.get('opt_out_in_hour'))
        hashed_unique_link = service.hashing_unique_link(unique_link)
        service.create_emergency_contact_approval_link(
            application.get('id'),
            unique_link,
            expiration_date
        )
        applications_data.append({
            'id': application.get('id'),
            'unique_link': unique_link,
            'hashed_unique_link': hashed_unique_link
        })

    if len(applications_data) > 0:
        sending_sms_async_worker.delay(applications_data)

    logger.info({
        "action": action,
        "status": "finish: {} data".format(len(application_ids))
    })


@task(queue="grab_global_queue")
def sending_sms_to_emergency_contact():
    from juloserver.grab.services.services import (
        EmergencyContactService,
        get_redis_client
    )

    service = EmergencyContactService(
        redis_client=get_redis_client(),
        sms_client=get_julo_sms_client()
    )

    action = "sending_sms_to_emergency_contact"
    logger.info({
        "action": action,
        "status": "starting"
    })

    parameters = service.get_feature_settings_parameters()
    if not parameters:
        logger.info({
            "action": action,
            "status": "feature settings not active"
        })
        return

    n_chunk = 50
    application_ids = []
    for application_id in service.pop_application_ids_from_redis():
        application_ids.append(application_id)
        if len(application_ids) == n_chunk:
            sending_sms_to_emergency_contact_worker(application_ids, parameters)
            application_ids = []

    if application_ids:
        sending_sms_to_emergency_contact_worker(application_ids, parameters)

    logger.info({
        "action": action,
        "status": "finished"
    })


@task(queue="grab_global_queue")
def emergency_contact_auto_reject():
    from juloserver.grab.services.services import (
        EmergencyContactService
    )

    action = "emergency_contact_auto_reject"
    logger.info({
        "action": action,
        "status": "starting"
    })

    service = EmergencyContactService(
        redis_client=None,
        sms_client=None
    )

    expired_ec_queryset = service.get_expired_emergency_approval_link_queryset()
    if expired_ec_queryset.exists():
        service.auto_reject_ec_consent(expired_ec_approval_link_qs=expired_ec_queryset)

    logger.info({
        "action": action,
        "status": "finished"
    })


@task(queue="grab_global_queue")
def resend_sms_to_emergency_contact_worker(filtered_ec_approval_link):
    action = "resend_sms_to_emergency_contact_worker"
    logger.info({
        "action": action,
        "status": "starting"
    })
    from juloserver.grab.services.services import (
        EmergencyContactService
    )

    service = EmergencyContactService(
        redis_client=None,
        sms_client=get_julo_sms_client()
    )

    applications_data = []
    for ec_link in filtered_ec_approval_link:
        application_id = ec_link.get('application_id')
        unique_link = ec_link.get('unique_link')
        hashed_unique_link = service.hashing_unique_link(unique_link)
        applications_data.append({
            'id': application_id,
            'unique_link': unique_link,
            'hashed_unique_link': hashed_unique_link
        })

    if len(applications_data) > 0:
        sending_sms_async_worker.delay(applications_data, True)

    action = "resend_sms_to_emergency_contact_worker"
    logger.info({
        "action": action,
        "status": "finish"
    })


@task(queue="grab_global_queue")
def resend_sms_to_emergency_contact():
    action = "resend_sms_to_emergency_contact"
    logger.info({
        "action": action,
        "status": "starting"
    })
    from juloserver.grab.services.services import (
        EmergencyContactService,
        get_redis_client
    )

    service = EmergencyContactService(
        redis_client=get_redis_client()
    )

    parameters = service.get_feature_settings_parameters()

    for application_data_json in service.pop_application_ids_from_redis(service.reapply_redis_key):
        application_data = json.loads(application_data_json)
        expiration_date = service.set_expired_time(parameters.get('opt_out_in_hour'))
        service.create_emergency_contact_approval_link(
            application_data.get('application_id'),
            application_data.get('unique_link'),
            expiration_date
        )

    for filtered_ec_approval_link in service.get_ec_that_need_to_resend_sms():
        if len(filtered_ec_approval_link) > 0:
            resend_sms_to_emergency_contact_worker(filtered_ec_approval_link)

    logger.info({
        "action": action,
        "status": "finish"
    })

@task(queue="grab_global_queue")
def delete_old_ec_approval_link():
    from juloserver.grab.services.services import (
        EmergencyContactService
    )

    service = EmergencyContactService(
        redis_client=None,
        sms_client=None
    )
    service.delete_old_emergency_contact_approval_link()


@task(queue="grab_global_queue")
def task_emergency_contact():
    from juloserver.grab.services.services import (
        EmergencyContactService
    )

    service = EmergencyContactService(
        redis_client=None,
        sms_client=None
    )

    action = "task_emergency_contact"
    logger.info({
        "action": action,
        "status": "starting"
    })

    parameters = service.get_feature_settings_parameters()
    if not parameters:
        logger.info({
            "action": action,
            "status": "feature settings not active"
        })
        return

    emergency_contact_auto_reject.delay()
    delete_old_ec_approval_link.delay()

    now = timezone.localtime(timezone.now())
    if parameters.get("sms_cron_send_time") != now.hour:
        return

    sending_sms_to_emergency_contact()

    logger.info({
        "action": action,
        "status": "done triggering child task"
    })


@task(queue="grab_global_queue")
def task_emergency_contact_resend_sms():
    from juloserver.grab.services.services import (
        EmergencyContactService
    )

    service = EmergencyContactService(
        redis_client=None,
        sms_client=None
    )

    action = "task_emergency_contact_resend_sms"
    logger.info({
        "action": action,
        "status": "starting"
    })

    parameters = service.get_feature_settings_parameters()
    if not parameters:
        logger.info({
            "action": action,
            "status": "feature settings not active"
        })
        return

    now = timezone.localtime(timezone.now())
    if parameters.get("sms_cron_send_time") + 1 != now.hour:
        return

    resend_sms_to_emergency_contact()

    logger.info({
        "action": action,
        "status": "done triggering child task"
    })


def generate_ajukan_pinjaman_lagi_info_card():
    from juloserver.streamlined_communication.models import CardProperty
    from juloserver.julo.models import Image
    from juloserver.grab.constants import INFO_CARD_AJUKAN_PINJAMAN_LAGI_DESC

    class ImageNames(object):
        DESIGNS_REAL = 'info-card/data_bg.png'


    def create_image(image_source_id, image_type, image_url):
        image = Image()
        image.image_source = image_source_id
        image.image_type = image_type
        image.url = image_url
        image.save()

    M_BUTTON = 'M.BUTTON'

    data = {
        'status': ApplicationStatusCodes.LOC_APPROVED,
        'additional_condition': CardProperty.GRAB_AJUKAN_PINJAMAN_LAGI,
        'title': 'Yuk, Lakukan Transaksi Lagi',
        'content': 'Klik <b>Pilih Pinjaman</b> untuk ajukan pinjaman lagi, ya!',
        'button': ['Pilih Pinjaman'],
        'button_name': [M_BUTTON],
        'click_to': ['/offer'],
        'template_type': '2',
        'card_number': 1,
        'text_colour': '#ffffff',
        'title_colour': '#ffffff',
        'background_url': ImageNames.DESIGNS_REAL,
        'additional_images': [],
        'button_url': [],
    }

    button_2_properties = {
        'card_type': '2',
        'title': data['title'],
        'title_color': data['title_colour'],
        'text_color': data['text_colour'],
        'card_order_number': data['card_number']
    }

    # info card
    info_card = InfoCardProperty.objects.create(**button_2_properties)

    # button
    button_info_card = dict()
    button_info_card['info_card_property'] = info_card
    button_info_card['text'] = data['button'][0]
    button_info_card['button_name'] = data['button_name'][0]
    button_info_card['action_type'] = CardProperty.WEBPAGE
    button_info_card['destination'] = data['click_to'][0]
    button_info_card['text_color'] = data['text_colour']
    InfoCardButtonProperty.objects.get_or_create(**button_info_card)

    # message
    data_streamlined_message = {
        'message_content': data['content'],
        'info_card_property': info_card
    }
    message = StreamlinedMessage.objects.create(**data_streamlined_message)
    status = StatusLookup.objects.filter(status_code=data['status']).last()
    data_for_streamlined_comms = {
        'status_code': status,
        'status': data['status'],
        'communication_platform': CommunicationPlatform.INFO_CARD,
        'message': message,
        'description': INFO_CARD_AJUKAN_PINJAMAN_LAGI_DESC,
        'is_active': True,
        'extra_conditions': data['additional_condition']
    }

    StreamlinedCommunication.objects.create(**data_for_streamlined_comms)

    # create image for background
    if data['background_url']:
        create_image(
            info_card.id,
            CardProperty.IMAGE_TYPE.card_background_image,
            data['background_url']
        )


def send_trigger_to_anaserver_status105(application):
    # continue action from 105 handler
    from juloserver.grab.workflows import GrabWorkflowAction
    workflow = GrabWorkflowAction(
        application=application,
        new_status_code=ApplicationStatusCodes.FORM_PARTIAL,
        change_reason="fdc check manual approval",
        note="fdc check manual approval",
        old_status_code=ApplicationStatusCodes.FORM_CREATED
    )
    workflow.update_customer_data()
    workflow.trigger_anaserver_status105()


def call_process_application_status_change(application):
    from juloserver.julo.services import process_application_status_change
    process_application_status_change(
        application.id, ApplicationStatusCodes.APPLICATION_DENIED, "system_triggered"
    )


@task(queue="grab_global_queue")
def process_application_status_change(chunked_fdc_check_manual_approval_objects):
    for chunked_fdc_check_manual_approval_object in chunked_fdc_check_manual_approval_objects:
        application = Application.objects.filter(
            id=chunked_fdc_check_manual_approval_object.application_id
        ).last()
        if application:
            if chunked_fdc_check_manual_approval_object.status == ApplicationStatus.APPROVE:
                send_trigger_to_anaserver_status105(application)
            elif chunked_fdc_check_manual_approval_object.status == ApplicationStatus.REJECT:
                fdc_inquiry = FDCInquiry.objects.filter(application=application).last()
                if (fdc_inquiry and fdc_inquiry.inquiry_status and
                        fdc_inquiry.inquiry_status.lower() in ['pending', 'failed']):
                    call_process_application_status_change(application)
