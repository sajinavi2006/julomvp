from collections import defaultdict
from celery import chain, group, task
import time
import logging
import os
import tempfile
import pdfkit
import csv
from typing import List, Optional

from croniter import croniter
from datetime import (
    datetime,
    time,
    timedelta,
)
from django.utils import timezone
from django.conf import settings

from django.db import transaction
from juloserver.fdc.files import TempDir

from juloserver.julo.clients import get_julo_sentry_client

from juloserver.disbursement.services import trigger_disburse

from juloserver.julo.statuses import (
    LoanStatusCodes, ApplicationStatusCodes,
)
from juloserver.julo.models import (
    Loan,
    Application,
    EmailHistory,
    Document,
    FeatureSetting,
    Partner,
    Payment,
)
from juloserver.julo.tasks import upload_document
from juloserver.julo.exceptions import JuloException
from juloserver.julo.clients import get_julo_email_client
from juloserver.julo.services import process_application_status_change
from juloserver.julo.constants import EmailTemplateConst, FeatureNameConst
from juloserver.julo.utils import (
    upload_file_to_oss,
    post_anaserver,
    format_e164_indo_phone_number,
    display_rupiah,
)

from juloserver.loan.services.lender_related import julo_one_disbursement_process
from juloserver.loan.services.loan_related import update_loan_status_and_loan_history
from juloserver.merchant_financing.services import (
    PartnerPaymentService,
    PartnerApplicationService,
    PartnerDisbursementService,
    PartnerLoanService,
    get_sphp_template_merhant_financing,
    emails_sign_sphp_merchant_financing_expired,
    get_sphp_loan_merchant_financing,
    get_axiata_disbursement_data,
    get_axiata_repayment_data,
    generate_merchant_historical_csv_file,
    update_late_fee_amount_mf_std,
    validate_merchant_historical_transaction_data,
    store_data_merchant_historical_transaction,
    mfsp_disbursement_pg_service,
    process_callback_transfer_result,
)
from juloserver.merchant_financing.models import (
    MerchantHistoricalTransactionTask,
    MerchantHistoricalTransactionTaskStatus
)
from juloserver.merchant_financing.constants import (
    MERCHANT_FINANCING_MAXIMUM_ONLINE_DISBURSEMENT,
    BulkDisbursementStatus,
    SPHPType,
    DocumentType,
    AxiataReportType,
    MerchantHistoricalTransactionTaskStatuses
)

from juloserver.partnership.constants import (
    PartnershipLoanStatusChangeReason,
    PartnershipFeatureNameConst,
)
from juloserver.partnership.services.services import store_merchant_historical_transaction

from .models import BulkDisbursementRequest, BulkDisbursementSchedule

from juloserver.julo.clients.sms import JuloSmsClient, PartnershipSMSClient
from juloserver.merchant_financing.utils import generate_skrtp_link
from juloserver.urlshortener.services import shorten_url
from juloserver.partnership.utils import partnership_detokenize_sync_object_model
from juloserver.pii_vault.constants import PiiSource
from juloserver.partnership.models import PartnershipFeatureSetting
from juloserver.julo.product_lines import ProductLineCodes

logger = logging.getLogger(__name__)


@task(name='task_va_payment_notification_to_partner', queue='partner_mf_global_queue')
def task_va_payment_notification_to_partner(payment_event):
    PartnerPaymentService.notify_partner(payment_event)


@task(name='task_application_status_change_notification_to_partner')
def task_application_status_change_notification_to_partner(application_id):
    PartnerApplicationService.notify_partner(application_id)


@task(name='task_digital_signature_change_notification_to_partner')
def task_digital_signature_change_notification_to_partner(loan_id):
    PartnerLoanService.notify_digital_signature_change_to_partner(loan_id)


@task(name='task_process_partner_application_async', queue='partner_mf_global_queue')
def task_process_partner_application_async(application_data, axiata_customer_data_obj):
    PartnerApplicationService.process_partner_application_async(
        application_data, axiata_customer_data_obj)


@task(name='task_upload_image_merchant_financing_async', queue='partner_mf_global_queue')
def task_upload_image_merchant_financing_async(image_id, thumbnail=True):
    PartnerApplicationService.upload_image_merchant_financing_async(image_id)


@task(name='task_process_disbursement_request_async', queue='partner_mf_global_queue')
def task_process_disbursement_request_async(partner_application_id, loan_xid):
    PartnerDisbursementService.process_disbursement_request_async(partner_application_id, loan_xid)


@task(name='task_disbursement_status_change_notification_to_partner', queue='partner_mf_global_queue')
def task_disbursement_status_change_notification_to_partner(loan_id):
    loan = Loan.objects.get(id=loan_id)
    PartnerDisbursementService.notify_partner(loan)


@task(name='kick_off_bulk_disbursement_midnight', queue='partner_mf_cronjob_queue')
def kick_off_bulk_disbursement_midnight():
    active_crons = BulkDisbursementSchedule.objects.filter(
        is_active=True,
        is_manual_disbursement=False
    )
    midnight_today = timezone.localtime(datetime.combine(
            timezone.localtime(timezone.now()).date(), time()))

    for cron in active_crons:
        croniter_data = croniter(cron.crontab, midnight_today)
        partner_id = cron.partner.id if cron.partner else None
        distributor_id = cron.distributor.id if cron.distributor else None
        while True:
            next_schedule = croniter_data.get_next(datetime)
            if next_schedule.day != midnight_today.day \
            or next_schedule.month != midnight_today.month:
                break
            trigger_partner_bulk_disbursement.apply_async(
                (cron.product_line_code,),
                kwargs={'partner_id': partner_id,
                        'distributor_id': distributor_id},
                eta=next_schedule)


@task(name='trigger_partner_bulk_disbursement', queue='partner_mf_global_queue')
def trigger_partner_bulk_disbursement(product_line_code, partner_id=None, distributor_id=None):
    disbursement_requests = BulkDisbursementRequest.objects.select_related('partner').filter(
        disbursement_status=BulkDisbursementStatus.QUEUE,
        product_line_code=product_line_code,
        partner_id=partner_id,
        distributor_id=distributor_id
    ).order_by('bank_account_number')
    # Add Feature Setting to filter out if request which have lower cdate
    # than the delay target
    partnership_feature_setting = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.PARTNERSHIP_BULK_DISBURSEMENT_DELAY,
        is_active=True
    ).last()
    if partnership_feature_setting:
        delayed_partner_name = list(partnership_feature_setting.parameters.keys())

        if len(disbursement_requests) > 0:
            partner_name = disbursement_requests[0].partner.name
            if partner_name in delayed_partner_name:
                delay = timedelta(**partnership_feature_setting.parameters[partner_name])
                disbursement_requests = disbursement_requests.filter(
                    cdate__lte=timezone.localtime(timezone.now() - delay)).order_by(
                    'bank_account_number')

    current_bank_number = None
    current_queue = []

    for disbursement in disbursement_requests:
        if disbursement.bank_account_number != current_bank_number:
            if current_queue:
                # send queue to subtask
                # current_bank_number, current_queue
                partner_bulk_disbursement_subtask.delay(current_queue, current_bank_number)

            # reset
            current_bank_number = disbursement.bank_account_number
            current_queue = []

        current_queue.append(disbursement.id)

    if current_queue:
        partner_bulk_disbursement_subtask.delay(current_queue, current_bank_number)


@task(name='partner_bulk_disbursement_subtask', queue='partner_mf_global_queue')
def partner_bulk_disbursement_subtask(disbursement_request_ids, bank_account_number):
    def today():
        return timezone.localtime(timezone.now())

    with transaction.atomic():
        disbursement_requests = BulkDisbursementRequest.objects.filter(
            disbursement_status=BulkDisbursementStatus.QUEUE,
            bank_account_number=bank_account_number,
            pk__in=disbursement_request_ids
        )
        result = disbursement_requests.update(
            disbursement_status=BulkDisbursementStatus.PENDING,
            udate=today())

        if result != len(disbursement_request_ids):
            logger.error({
                'action': 'partner_bulk_disbursement_subtask',
                'data': (disbursement_request_ids, bank_account_number),
                'msg': 'Can not update status'
            })
            raise Exception('Can not update status')

    from juloserver.loan.services.loan_related import update_loan_status_and_loan_history
    from juloserver.loan.services.lender_related import julo_one_loan_disbursement_success

    disbursement_requests = BulkDisbursementRequest.objects.filter(pk__in=disbursement_request_ids)

    total_amount = 0
    original_amount = 0
    name_bank_validation_id = None
    for request in disbursement_requests:
        total_amount += request.disbursement_amount
        original_amount += request.loan_amount
        last_loan_xid = request.loan.loan_xid
        name_bank_validation_id = request.name_bank_validation_id

    data_bulk_disburse = {
        'disbursement_id': None,
        'name_bank_validation_id': name_bank_validation_id,
        'amount': total_amount,
        'external_id': last_loan_xid,
        'type': 'loan bulk',
        'original_amount': original_amount
    }

    disbursement = trigger_disburse(data_bulk_disburse, method='Bca')
    disbursement_id = disbursement.get_id()

    loan_ids = disbursement_requests.values_list('loan_id', flat=True)
    Loan.objects.filter(pk__in=loan_ids).update(disbursement_id=disbursement_id)

    disbursement_requests.update(
        disbursement_id=disbursement_id,
        udate=today())

    try:
        disbursement.disburse()
        is_success = disbursement.is_success()
    except Exception as error:
        sentry_client = get_julo_sentry_client()
        sentry_client.captureException()
        is_success = False

    if is_success:
        disbursement_requests.update(
            disbursement_status=BulkDisbursementStatus.COMPLETED,
            udate=today())
    else:
        disbursement_requests.update(
            disbursement_status=BulkDisbursementStatus.FAILED,
            udate=today())

    for request in disbursement_requests:
        if is_success:
            julo_one_loan_disbursement_success(request.loan)
        else:
            update_loan_status_and_loan_history(
                request.loan.id,
                new_status_code=LoanStatusCodes.MANUAL_FUND_DISBURSAL_ONGOING,
                change_reason="Manual disbursement"
            )


@task(name='send_email_sign_sphp_merchant_financing', queue='partner_mf_global_queue')
def send_email_sign_sphp_merchant_financing(application_id):
    application = Application.objects.get_or_none(pk=application_id)
    customer = application.customer
    julo_email_client = get_julo_email_client()

    base_julo_web_url = settings.JULO_WEB_URL
    if settings.ENVIRONMENT != 'prod':
        base_julo_web_url = "https://app-staging1.julo.co.id"
    login_url = "/view/login?page=sphp&partner_category=merchant_financing"
    sign_link = base_julo_web_url + login_url
    status, headers, subject, msg = julo_email_client.email_sign_sphp_general(
        application, sign_link
    )
    template_code = EmailTemplateConst.SIGN_SPHP_MERCHANT_FINANCING

    EmailHistory.objects.create(
        customer=customer,
        sg_message_id=headers["X-Message-Id"],
        to_email=customer.email,
        subject=subject,
        application=application,
        message_content=msg,
        template_code=template_code,
    )

    logger.info({
        "action": "send_email_sign_sphp_merchant_financing",
        "customer_id": customer.id,
        "template_code": template_code
    })


@task(name='generate_sphp_merchant_financing', queue='partner_mf_global_queue')
def generate_sphp_merchant_financing(application_id):
    application = Application.objects.get_or_none(pk=application_id)
    if not application:
        logger.error({
            'action_view': 'generate_sphp_merchant_financing',
            'data': {'application_id': application_id},
            'errors': "Application tidak ditemukan."
        })
        return

    try:
        document = Document.objects.get_or_none(document_source=application_id,
                                                document_type=DocumentType.SPHP_JULO)
        if document:
            logger.error({
                'action_view': 'generate_sphp_merchant_financing',
                'data': {'application_id': application_id, 'document': document.filename},
                'errors': "sphp has found"
            })
            return

        body = get_sphp_template_merhant_financing(application_id, SPHPType.DOCUMENT)
        if not body:
            logger.error({
                'action_view': 'generate_sphp_merchant_financing',
                'data': {'application_id': application_id},
                'errors': "Template tidak ditemukan."
            })
            return
        now = datetime.now()
        filename = '{}_{}_{}_{}.pdf'.format(
            application.fullname,
            application.application_xid,
            now.strftime("%Y%m%d"),
            now.strftime("%H%M%S"))
        file_path = os.path.join(tempfile.gettempdir(), filename)

        try:
            pdfkit.from_string(body, file_path)
        except Exception as e:
            logger.error({
                'action_view': 'generate_sphp_merchant_financing',
                'data': {'application_id': application_id},
                'errors': str(e)
            })
            return

        sphp_julo = Document.objects.create(document_source=application.id,
                                            document_type=DocumentType.SPHP_JULO,
                                            filename=filename,
                                            application_xid=application.application_xid)

        logger.info({
            'action_view': 'generate_sphp_merchant_financing',
            'data': {'application_id': application_id, 'document_id': sphp_julo.id},
            'message': "success create PDF"
        })

        upload_document(sphp_julo.id, file_path)

    except Exception as e:
        logger.error({
            'action_view': 'generate_sphp_merchant_financing',
            'data': {'application_id': application_id},
            'errors': str(e)
        })
        JuloException(e)


@task(name='upload_sphp_to_oss_merchant_financing', queue='partner_mf_global_queue')
def upload_sphp_to_oss_merchant_financing(application_id):
    application = Application.objects.get_or_none(id=application_id)
    if not application:
        return
    logger.info({
        "task": "upload_sphp_to_oss_merchant_financing",
        "application_id": application.id
    })
    document = Document.objects.filter(
        document_source=application.id,
        application_xid=application.application_xid,
        document_type=DocumentType.SPHP_JULO,
    ).last()

    if not document:
        generate_sphp_merchant_financing.delay(application.id)


@task(name='check_emails_sign_sphp_merchant_financing_expired', queue='partner_mf_cronjob_queue')
def check_emails_sign_sphp_merchant_financing_expired():
    emails_sign_sphp_expired = emails_sign_sphp_merchant_financing_expired()
    if not emails_sign_sphp_expired:
        return

    for email_sphp_expired in emails_sign_sphp_expired:
        process_application_status_change(
            email_sphp_expired.application.id, ApplicationStatusCodes.APPLICATION_DENIED,
            change_reason='sphp_rejected'
        )


@task
def generate_sphp_loan_merchant_financing(loan_id: int) -> None:
    loan = Loan.objects.select_related('account').filter(pk=loan_id).last()
    if not loan:
        logger.error({
            'action_view': 'generate_sphp_loan_merchant_financing',
            'data': {'loan_id': loan_id},
            'errors': "loan not found."
        })
        return

    try:
        document = Document.objects.get_or_none(document_source=loan_id,
                                                document_type=DocumentType.SPHP_JULO)
        if document:
            logger.error({
                'action_view': 'generate_sphp_loan_merchant_financing',
                'data': {'loan_id': loan_id, 'document': document.filename},
                'errors': "sphp has found"
            })
            return

        body = get_sphp_loan_merchant_financing(loan_id)
        if not body:
            logger.error({
                'action_view': 'generate_sphp_loan_merchant_financing',
                'data': {'loan_id': loan_id},
                'errors': "Template not found"
            })
            return
        now = datetime.now()
        application = loan.account.last_application
        filename = '{}_{}_{}_{}.pdf'.format(
            application.fullname,
            application.application_xid,
            now.strftime("%Y%m%d"),
            now.strftime("%H%M%S"))
        file_path = os.path.join(tempfile.gettempdir(), filename)

        try:
            pdfkit.from_string(body, file_path)
        except Exception as e:
            logger.error({
                'action_view': 'generate_sphp_loan_merchant_financing',
                'data': {'loan_id': loan_id},
                'errors': str(e)
            })
            return

        sphp_julo = Document.objects.create(document_source=loan_id,
                                            document_type=DocumentType.SPHP_JULO,
                                            filename=filename,
                                            loan_xid=loan.loan_xid)

        logger.info({
            'action_view': 'generate_sphp_loan_merchant_financing',
            'data': {'loan_id': loan_id, 'document_id': sphp_julo.id},
            'message': "success create PDF"
        })

        upload_document(sphp_julo.id, file_path, is_loan=True)

    except Exception as e:
        logger.error({
            'action_view': 'generate_sphp_loan_merchant_financing',
            'data': {'loan_id': loan_id},
            'errors': str(e)
        })
        JuloException(e)


@task(name='upload_sphp_loan_merchant_financing_to_oss', queue='partner_mf_global_queue')
def upload_sphp_loan_merchant_financing_to_oss(loan_id: int) -> None:
    loan = Loan.objects.get_or_none(id=loan_id)
    if not loan:
        logger.error({
            "task": "upload_sphp_loan_merchant_financing_to_oss",
            "loan_id": loan_id,
            "errors": "loan not found"
        })
        return
    logger.info({
        "task": "upload_sphp_loan_merchant_financing_to_oss",
        "loan_id": loan_id
    })
    document = Document.objects.filter(
        document_source=loan_id,
        loan_xid=loan.loan_xid,
        document_type=DocumentType.SPHP_JULO,
    ).last()

    if not document:
        generate_sphp_loan_merchant_financing.delay(loan_id)


@task(name='upload_axiata_disbursement_and_repayment_data_to_oss', queue='partner_axiata_cronjob_queue')
def upload_axiata_disbursement_and_repayment_data_to_oss():
    today_date = timezone.localtime(timezone.now()).date()

    yesterday_date = today_date - timedelta(days=1)

    yesterday_date_formatted = yesterday_date.strftime('%Y-%m-%d')
    disbursement_data = get_axiata_disbursement_data(yesterday_date_formatted)
    repayment_data = get_axiata_repayment_data(yesterday_date_formatted)
    if disbursement_data:
        upload_axiata_report_data_to_oss.delay(disbursement_data, yesterday_date,
                                               AxiataReportType.DISBURSEMENT)
    if repayment_data:
        upload_axiata_report_data_to_oss.delay(repayment_data, yesterday_date,
                                               AxiataReportType.REPAYMENT)


@task(name='upload_axiata_report_data_to_oss', queue='partner_axiata_global_queue')
def upload_axiata_report_data_to_oss(data: list, date: datetime, report_type: str) -> None:
    try:
        temp_dir = tempfile.gettempdir()
        # header disbursement
        header = ('register_date', 'application_xid', 'fullname', 'brand_name', 'ktp',
                  'mobile_phone_1', 'distributor_name', 'loan_amount', 'disbursed_amount',
                  'status_disbursement', 'disbursed_date', 'partner_application_date',
                  'acceptance_date', 'account_number', 'funder',
                  'due_date', 'due_amount','interest', 'provision')

        if report_type == AxiataReportType.REPAYMENT:
            # header repayment
            header = ('register_date', 'application_xid', 'payment_amount', 'payment_number',
                      'invoice_idip_address', 'due_date', 'payment_date', 'payment_upload_date',
                      'dpd', 'interest_amount', 'late_fee_amount', 'mobile_phone_1', 'fullname',
                      'brand_name', 'distributor_name', 'loan_amount', 'due_amount', 'paid_amount',
                      'status', 'julo_bank_name', 'julo_bank_account_number', 'funder')
        date_formatted = int(date.strftime("%Y%m%d"))
        file_name = '{}_{}.csv'.format(report_type, date_formatted)
        file_path = os.path.join(temp_dir, file_name)
        with open(file_path, 'w', newline='') as f:
            writer = csv.writer(f, delimiter='|')
            writer.writerow(header)
            writer.writerows(data)

        document_remote_filepath = 'axiata/report/{}'.format(file_name)
        upload_file_to_oss(settings.OSS_MEDIA_BUCKET, file_path, document_remote_filepath)
        Document.objects.create(
            document_source=date_formatted,
            document_type=report_type,
            filename=file_name,
            url=document_remote_filepath,
            service='oss'
        )

        if os.path.exists(file_path):
            os.remove(file_path)
    except Exception as e:
        logger.error({
            "action": "upload_axiata_report_data_to_oss",
            "error": str(e),
            "report_type": report_type,
            "date": date
        })


@task(name='process_validate_merchant_historical_transaction', queue='partner_mf_merchant_historical_transaction_queue')
def process_validate_merchant_historical_transaction(
    merchant_historical_transaction_task_id,
    unique_id: int, application_id: int, file_path: Optional[str] = None,
    data_merchant_historical_transaction: Optional[list] = None,
    csv_file: bytes =None, csv_file_name: str = ''
) -> None:
    if not file_path and not data_merchant_historical_transaction and not csv_file:
        return

    application = Application.objects.get(id=application_id)
    merchant_historical_transaction_task =\
        MerchantHistoricalTransactionTask.objects.select_related(
            'merchanthistoricaltransactiontaskstatus'
        ).get(id=merchant_historical_transaction_task_id)
    merchant_historical_transaction_task_status =\
        merchant_historical_transaction_task.merchanthistoricaltransactiontaskstatus

    with TempDir(dir="/media") as tempdir:
        if csv_file:
            if not csv_file_name:
                csv_file_name = 'uploaded'
            filename = '%s_%s.csv' % (csv_file_name, unique_id)
            dir_path = tempdir.path
            file_path = os.path.join(dir_path, filename)
            with open(file_path, "wb+") as f:
                f.write(csv_file)

        if file_path:
            with open(file_path, newline='') as csv_file:
                reader = csv.DictReader(csv_file)
                data_merchant_historical_transaction = list(reader)

        is_valid, validated_data = validate_merchant_historical_transaction_data(
            data_merchant_historical_transaction
        )

        # Not file_path mean it is a JSON that being uploaded
        if not file_path and data_merchant_historical_transaction:
            if is_valid:
                file_path = generate_merchant_historical_csv_file(
                    data_merchant_historical_transaction, unique_id,
                    dir_path=dir_path
                )
            else:
                file_path = generate_merchant_historical_csv_file(
                    data_merchant_historical_transaction, unique_id,
                    dir_path=dir_path
                )
                error_file_path = generate_merchant_historical_csv_file(
                    data=validated_data,
                    unique_id=merchant_historical_transaction_task.unique_id,
                    csv_type='error',
                    dir_path=dir_path
                )
                file_name = os.path.basename(file_path)
                merchant_historical_transaction_task.file_name = file_name
                merchant_historical_transaction_task.save()
                merchant_historical_transaction_task_status.status = MerchantHistoricalTransactionTaskStatuses.INVALID
                merchant_historical_transaction_task_status.save()

                store_data_merchant_historical_transaction(
                    file_path, application.id, merchant_historical_transaction_task.id, 'merchant_historical_transaction_data'
                )
                store_data_merchant_historical_transaction(
                    error_file_path, application.id, merchant_historical_transaction_task.id, 'merchant_historical_transaction_data_invalid'
                )

                if application.application_status.status_code == ApplicationStatusCodes.FORM_PARTIAL:
                    process_application_status_change(
                        application.id, ApplicationStatusCodes.MERCHANT_HISTORICAL_TRANSACTION_INVALID,
                        change_reason='invalid_historical_transaction')
                return

        file_name = os.path.basename(file_path)
        merchant_historical_transaction_task.file_name = file_name
        merchant_historical_transaction_task.save()

        store_data_merchant_historical_transaction(
            file_path, application.id, merchant_historical_transaction_task.id, 'merchant_historical_transaction_data'
        )

        if application.application_status.status_code == ApplicationStatusCodes.MERCHANT_HISTORICAL_TRANSACTION_INVALID:
            process_application_status_change(
                application.id, ApplicationStatusCodes.FORM_PARTIAL,
                change_reason='reupload merchant histrocial transaction')

        application.refresh_from_db()
        if is_valid:
            store_merchant_historical_transaction(application, validated_data, merchant_historical_transaction_task.id)
            merchant_historical_transaction_task_status.status = MerchantHistoricalTransactionTaskStatuses.VALID
            merchant_historical_transaction_task_status.save()

            if application.application_status.status_code == ApplicationStatusCodes.FORM_PARTIAL:
                # Call ana if the application status code already 105
                ana_data = {'application_id': application.id}
                url = '/api/amp/v1/merchant-form/'
                post_anaserver(url, json=ana_data)
        else:
            error_file_path = generate_merchant_historical_csv_file(
                data=validated_data,
                unique_id=merchant_historical_transaction_task.unique_id,
                csv_type='error',
                dir_path=dir_path
            )

            store_data_merchant_historical_transaction(
                error_file_path, application.id, merchant_historical_transaction_task.id, 'merchant_historical_transaction_data_invalid'
            )
            merchant_historical_transaction_task_status.status = MerchantHistoricalTransactionTaskStatuses.INVALID
            merchant_historical_transaction_task_status.save()

            if application.application_status.status_code == ApplicationStatusCodes.FORM_PARTIAL:
                process_application_status_change(
                    application.id, ApplicationStatusCodes.MERCHANT_HISTORICAL_TRANSACTION_INVALID,
                    change_reason='invalid_historical_transaction')


@task(queue='partner_mf_global_queue')
def process_merchant_financing_register(upload_async_state_id: int, partner_id: int) -> None:
    from juloserver.julo.constants import (UploadAsyncStateStatus, UploadAsyncStateType)
    from juloserver.julo.models import UploadAsyncState
    from juloserver.merchant_financing.services import register_mf_upload

    upload_async_state = UploadAsyncState.objects.filter(
        id=upload_async_state_id,
        task_type=UploadAsyncStateType.MERCHANT_FINANCING_REGISTER,
        task_status=UploadAsyncStateStatus.WAITING,
    ).first()

    partner = Partner.objects.get(id=partner_id)
    if not upload_async_state or not upload_async_state.file:
        logger.info(
            {
                "action": "process_merchant_financing_register",
                "message": "File not found",
                "upload_async_state_id": upload_async_state_id,
            }
        )

        if upload_async_state:
            upload_async_state.update_safely(task_status=UploadAsyncStateStatus.FAILED)

        return

    upload_async_state.update_safely(task_status=UploadAsyncStateStatus.PROCESSING)

    try:
        is_success_all = register_mf_upload(upload_async_state, partner)
        if is_success_all:
            task_status = UploadAsyncStateStatus.COMPLETED
        else:
            task_status = UploadAsyncStateStatus.PARTIAL_COMPLETED
        upload_async_state.update_safely(task_status=task_status)
    except Exception as e:
        logger.exception(
            {
                'module': 'merchant_financing',
                'action': 'process_merchant_financing_register',
                'upload_async_state_id': upload_async_state_id,
                'error': e,
            }
        )
        upload_async_state.update_safely(task_status=UploadAsyncStateStatus.FAILED)


@task(name='process_merchant_financing_disbursement', queue='partner_mf_global_queue')
def process_merchant_financing_disbursement(upload_async_state_id: int, partner_id: int) -> None:
    from juloserver.julo.constants import (UploadAsyncStateStatus, UploadAsyncStateType)
    from juloserver.julo.models import UploadAsyncState
    from juloserver.merchant_financing.services import disburse_mf_upload

    upload_async_state = UploadAsyncState.objects.filter(
        id=upload_async_state_id,
        task_type=UploadAsyncStateType.MERCHANT_FINANCING_DISBURSEMENT,
        task_status=UploadAsyncStateStatus.WAITING,
    ).first()

    partner = Partner.objects.get(id=partner_id)
    if not upload_async_state or not upload_async_state.file:
        logger.info(
            {
                "action": "process_merchant_financing_disbursement",
                "message": "File not found",
                "upload_async_state_id": upload_async_state_id,
            }
        )

        if upload_async_state:
            upload_async_state.update_safely(task_status=UploadAsyncStateStatus.FAILED)

        return

    upload_async_state.update_safely(task_status=UploadAsyncStateStatus.PROCESSING)

    try:
        is_success_all = disburse_mf_upload(upload_async_state, partner)
        if is_success_all:
            task_status = UploadAsyncStateStatus.COMPLETED
        else:
            task_status = UploadAsyncStateStatus.PARTIAL_COMPLETED
        upload_async_state.update_safely(task_status=task_status)
    except Exception as e:
        logger.exception(
            {
                'module': 'merchant_financing',
                'action': 'process_merchant_financing_disbursement',
                'upload_async_state_id': upload_async_state_id,
                'error': e,
            }
        )
        upload_async_state.update_safely(task_status=UploadAsyncStateStatus.FAILED)


@task(name='process_merchant_financing_adjust_limit', queue='partner_mf_global_queue')
def process_merchant_financing_adjust_limit(upload_async_state_id: int, partner_id: int) -> None:
    from juloserver.julo.constants import (UploadAsyncStateStatus, UploadAsyncStateType)
    from juloserver.julo.models import UploadAsyncState
    from juloserver.merchant_financing.services import adjust_limit_mf_upload

    upload_async_state = UploadAsyncState.objects.filter(
        id=upload_async_state_id,
        task_type=UploadAsyncStateType.MERCHANT_FINANCING_ADJUST_LIMIT,
        task_status=UploadAsyncStateStatus.WAITING,
    ).first()

    partner = Partner.objects.get(id=partner_id)
    if not upload_async_state or not upload_async_state.file:
        logger.info(
            {
                "action": "process_merchant_financing_adjust_limit",
                "message": "File not found",
                "upload_async_state_id": upload_async_state_id,
            }
        )

        if upload_async_state:
            upload_async_state.update_safely(task_status=UploadAsyncStateStatus.FAILED)

        return

    upload_async_state.update_safely(task_status=UploadAsyncStateStatus.PROCESSING)

    try:
        is_success_all = adjust_limit_mf_upload(upload_async_state, partner)
        if is_success_all:
            task_status = UploadAsyncStateStatus.COMPLETED
        else:
            task_status = UploadAsyncStateStatus.PARTIAL_COMPLETED
        upload_async_state.update_safely(task_status=task_status)
    except Exception as e:
        logger.exception(
            {
                'module': 'merchant_financing',
                'action': 'process_merchant_financing_adjust_limit',
                'upload_async_state_id': upload_async_state_id,
                'error': e,
            }
        )
        upload_async_state.update_safely(task_status=UploadAsyncStateStatus.FAILED)


@task(queue='partner_mf_global_queue')
def mf_send_sms(application_id, message) -> None:
    from juloserver.merchant_financing.utils import get_fs_send_skrtp_option_by_partner
    try:
        application = Application.objects.filter(pk=application_id).last()
        if not application:
            logger.error(
                {
                    'action': 'mf_send_sms',
                    'application_id': application_id,
                    'message': message,
                    'error': 'application not found',
                }
            )
            return
        partnership_customer_data = application.partnership_customer_data
        detokenize_partnership_customer_data = partnership_detokenize_sync_object_model(
            PiiSource.PARTNERSHIP_CUSTOMER_DATA,
            partnership_customer_data,
            partnership_customer_data.customer.customer_xid,
            ['phone_number'],
        )
        phone_number = format_e164_indo_phone_number(
            detokenize_partnership_customer_data.phone_number
        )
        partner_name = application.partner.name_detokenized
        err_msg, _, partner_phone_number = get_fs_send_skrtp_option_by_partner(partner_name)
        if err_msg:
            logger.error(
                {
                    'action': 'mf_send_sms',
                    'application_id': str(application_id),
                    'phone_number': phone_number,
                    'message': err_msg,
                }
            )
            return

        if partner_phone_number:
            phone_number = partner_phone_number

        sms_client = PartnershipSMSClient(
            settings.PARTNERSHIP_SMS_API_KEY,
            settings.PARTNERSHIP_SMS_API_SECRET,
            settings.PARTNERSHIP_SMS_API_BASE_URL,
        )
        sms_client.send_sms(phone_number, message, 'mf_send_skrtp_sms', 'mf_send_skrtp')

    except Exception as e:
        logger.exception(
            {
                'action': 'mf_send_sms',
                'application_id': application_id,
                'message': message,
                'error': e,
            }
        )


@task(queue='partner_mf_global_queue')
def mf_send_sms_skrtp(loan_id, timestamp):
    loan = Loan.objects.filter(id=loan_id).last()
    skrtp_url = generate_skrtp_link(loan, timestamp)
    skrtp_short_url = shorten_url(skrtp_url)
    message = 'Pengajuan Pinjaman sebesar {} sedang diproses. Konfirmasi pinjamanmu di {} dalam 1x24 jam kedepan.'.format(
        display_rupiah(loan.loan_amount), skrtp_short_url
    )
    application = loan.get_application

    mf_send_sms(application.id, message)


@task(queue='partner_mf_global_queue')
def upload_document_mf(document_id, document_category, local_path) -> None:
    document = Document.objects.get_or_none(pk=document_id)
    if not document:
        logger.error(
            {
                "action": "upload_document_mf",
                "message": "Document not found",
                "document_id": document_id,
            }
        )
        return

    if document_category == 'loan':
        loan = Loan.objects.get_or_none(pk=document.document_source)
        if not loan:
            logger.error(
                {
                    "action": "upload_document_mf",
                    "message": "Loan not found",
                    "document_id": document_id,
                }
            )
            return

        document.url = "cust_{}/{}_{}/{}".format(
            loan.customer.id, document_category, document.document_source, document.filename
        )

    try:
        upload_file_to_oss(settings.OSS_MEDIA_BUCKET, local_path, document.url)
        document.save()

    except Exception as e:
        logger.exception(
            {
                'action': 'upload_document_mf',
                'document_id': document_id,
                'document_url': document.url,
                'local_path': local_path,
                'error': e,
            }
        )

    if os.path.isfile(local_path):
        os.remove(local_path)


@task(queue="partner_mf_global_queue")
def generate_mf_std_skrtp(loan_id):
    from juloserver.partnership.models import (
        PartnershipDocument,
    )
    from juloserver.portal.object.bulk_upload.skrtp_service.service import get_mf_std_skrtp_content
    from juloserver.merchant_financing.web_app.utils import get_application_dictionaries

    loan = Loan.objects.select_related("lender").filter(id=loan_id).last()
    application = Application.objects.filter(id=loan.application_id2).last()
    partner_loan_request = loan.partnerloanrequest_set.last()
    product_lookup = loan.product
    account_limit = loan.account.accountlimit_set.last()

    application_dicts = get_application_dictionaries([partner_loan_request])

    detokenize_application = partnership_detokenize_sync_object_model(
        PiiSource.APPLICATION,
        application,
        application.customer.customer_xid,
        ['fullname'],
    )
    now = timezone.localtime(timezone.now()).date()
    filename = '{}_{}_{}_{}.pdf'.format(
        detokenize_application.fullname,
        loan.loan_xid,
        now.strftime("%Y%m%d"),
        now.strftime("%H%M%S"),
    )
    file_path = os.path.join(tempfile.gettempdir(), filename)

    partner_name = application.partner.name
    document = PartnershipDocument.objects.get_or_none(
        document_source=loan.id, document_type=f"{partner_name.lower()}_skrtp"
    )
    if document:
        return {
            "action": "generate_mf_std_skrtp",
            "loan_id": loan.id,
            "document_id": document.id,
            "document_url": document.document_url_api,
            "file_path": file_path,
            "error": "",
            "message": "document has found",
        }

    template = get_mf_std_skrtp_content(
        loan,
        application,
        partner_loan_request,
        product_lookup,
        application_dicts,
        account_limit,
    )
    if not template:
        response = {
            "action": "generate_mf_std_skrtp",
            "loan_id": loan.id,
            "document_id": "",
            "document_url": "",
            "file_path": file_path,
            "error": "SKRTP template not found",
            "message": "SKRTP template not found",
        }
        logger.error(response)

        return response

    try:
        pdfkit.from_string(template, file_path)

        skrtp_julo = PartnershipDocument.objects.create(
            document_source=loan.id,
            document_type=f"{partner_name.lower()}_skrtp",
            filename=filename,
        )

        skrtp_julo.url = "cust_{}/loan_{}/{}".format(loan.customer.id, loan.id, filename)

        upload_file_to_oss(settings.OSS_MEDIA_BUCKET, file_path, skrtp_julo.url)
        skrtp_julo.save()

        if os.path.isfile(file_path):
            os.remove(file_path)

        return {
            "action": "generate_mf_std_skrtp",
            "loan_id": loan.id,
            "document_id": skrtp_julo.id,
            "document_url": skrtp_julo.document_url_api,
            "file_path": file_path,
            "error": "",
            "message": "success create PDF",
        }
    except Exception as e:
        response = {
            "action": "generate_mf_std_skrtp",
            "loan_id": loan.id,
            "document_id": "",
            "document_url": "",
            "file_path": file_path,
            "error": str(e),
            "message": "PDF creation failed",
        }
        logger.error(response)

        return response


@task(queue='partner_mf_global_queue')
def update_late_fee_amount_mf_std_scheduler_task() -> None:
    unpaid_payments = (
        Payment.objects.not_paid_active_overdue()
        .filter(loan__account__account_lookup__name='Partnership Merchant Financing')
        .values_list("id", "account_payment__account__id")
        .order_by('id')
    )

    mapping_account_from_payments = defaultdict(list)
    for payment in unpaid_payments.iterator():
        account_id = payment[1]
        mapping_account_from_payments[account_id].append(payment[0])

    account_id_keys = list(mapping_account_from_payments.keys())
    chunks = [account_id_keys[i : i + 20] for i in range(0, len(account_id_keys), 20)]

    for chunk in chunks:
        chain_tasks = []
        for account_id in chunk:
            payment_ids = mapping_account_from_payments[account_id]
            chain_tasks.append(update_late_fee_amount_mf_std_task.si(payment_ids))
        group_tasks = group(chain(*chain_tasks))
        group_tasks()


@task(queue='partner_mf_global_queue')
def update_late_fee_amount_mf_std_task(payment_ids: List) -> None:
    logger.info(
        {
            "task": "update_late_fee_amount_mf_std_task",
            "payment_ids": payment_ids,
        }
    )

    for payment_id in payment_ids:
        update_late_fee_amount_mf_std(payment_id)


@task(queue="partner_mf_global_queue")
def merchant_financing_disbursement_process_task(loan_id):
    loan = Loan.objects.get_or_none(pk=loan_id)
    if not loan:
        logger.error(
            {
                "action_view": "merchant_financing_disbursement_process_task",
                "loan_id": loan_id,
                "message": "Loan ID not found!!",
            }
        )
        return

    if loan.loan_amount >= MERCHANT_FINANCING_MAXIMUM_ONLINE_DISBURSEMENT:
        update_loan_status_and_loan_history(
            loan.id,
            new_status_code=LoanStatusCodes.MANUAL_FUND_DISBURSAL_ONGOING,
            change_reason=PartnershipLoanStatusChangeReason.MANUAL_DISBURSEMENT,
        )
        logger.info(
            {
                "action_view": "merchant_financing_disbursement_process_task",
                "loan_id": loan.id,
                "message": "loan amount more than 1 bio: {}".format(loan.loan_amount),
            }
        )
    else:
        is_pg_service_active = PartnershipFeatureSetting.objects.filter(
            feature_name=PartnershipFeatureNameConst.MFSP_PG_SERVICE_ENABLEMENT,
            is_active=True,
        ).exists()
        if (
            is_pg_service_active
            and loan.product.product_line_id == ProductLineCodes.MERCHANT_FINANCING_STANDARD_PRODUCT
        ):
            err = mfsp_disbursement_pg_service(loan_id)
            if err:
                logger.error(
                    {
                        "action_view": "merchant_financing_disbursement_process_task",
                        "action_service": "mfsp_disbursement_pg_service",
                        "loan_id": loan_id,
                        "message": err,
                    }
                )
        else:
            julo_one_disbursement_process(loan)


@task(
    name="merchant_financing_generate_lender_agreement_document_task",
    queue="partner_mf_global_queue",
)
def merchant_financing_generate_lender_agreement_document_task(loan_id):
    from juloserver.merchant_financing.services import (
        merchant_financing_generate_auto_lender_agreement_document,
    )

    merchant_financing_generate_auto_lender_agreement_document(loan_id)


@task(queue='partner_mf_global_queue')
def process_callback_transfer_result_task(transaction_id, status) -> None:
    logger.info(
        {
            "task": "process_callback_transfer_result_task",
            "transaction_id": transaction_id,
            "status": status,
            "message": "Received",
        }
    )
    try:
        err = process_callback_transfer_result(transaction_id, status)
        if err:
            logger.error(
                {
                    "task": "process_callback_transfer_result_task",
                    "transaction_id": transaction_id,
                    "status": status,
                    "message": "Error process_callback_transfer_result",
                    "error": err,
                }
            )

    except Exception as e:
        logger.error(
            {
                "task": "process_callback_transfer_result_task",
                "transaction_id": transaction_id,
                "status": status,
                "message": "Error Exception",
                "error": str(e),
            }
        )
        return
