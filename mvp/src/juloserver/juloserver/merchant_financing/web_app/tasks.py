import logging
import base64
import time

from collections import defaultdict
from typing import List

from celery import chain, group, task
from datetime import timedelta

from django.conf import settings
from django.utils import timezone
from django.db import transaction
from django.template.loader import render_to_string, get_template

from juloserver.application_flow.constants import PartnerNameConstant
from juloserver.fdc.files import TempDir
from juloserver.julo.clients import get_julo_email_client
from juloserver.julo.constants import UploadAsyncStateStatus
from juloserver.julo.exceptions import JuloException
from juloserver.julo.models import Loan, Partner, EmailHistory, UploadAsyncState, ApplicationNote
from juloserver.julo.models import Payment, FeatureSetting
from juloserver.julo.statuses import ApplicationStatusCodes, LoanStatusCodes
from juloserver.merchant_financing.constants import MFFeatureSetting
from juloserver.merchant_financing.web_app.services import (
    axiata_update_late_fee_amount,
    process_merchant_upload,
    validate_dukcapil_fr_partnership,
)
from juloserver.julo.services import process_application_status_change
from juloserver.partnership.constants import PartnershipAccountLookup
from juloserver.partnership.constants import PartnershipImageProductType
from juloserver.partnership.models import PartnershipApplicationData
from juloserver.merchant_financing.web_app.services import generate_csv_for_new_merchant
from juloserver.merchant_financing.web_app.constants import (
    EMAIL_SENDER_FOR_AXIATA,
    MFWebAppUploadAsyncStateType,
)
import juloserver.pin.services as password_services
from juloserver.partnership.utils import (
    partnership_detokenize_sync_object_model,
    generate_pii_filter_query_partnership,
)
from juloserver.personal_data_verification.exceptions import SelfieImageNotFound
from juloserver.personal_data_verification.models import DukcapilFaceRecognitionCheck
from juloserver.personal_data_verification.services import DukcapilFRService
from juloserver.pii_vault.constants import PiiSource, PiiVaultDataType
from juloserver.merchant_financing.web_app.services import generate_axiata_customer_data
from juloserver.sdk.models import AxiataCustomerData

logger = logging.getLogger(__name__)


@task(queue='partner_mf_global_queue')
def send_list_new_merchant_financing_axiata():
    # Generate CSV
    pii_filter_dict = generate_pii_filter_query_partnership(
        Partner, {'name': PartnershipImageProductType.AXIATA.lower()}
    )
    partner = Partner.objects.filter(is_active=True, **pii_filter_dict).last()

    if not partner:
        logger.warning(
            {
                'action_view': 'failed_send_report_new_merchant_to_axiata',
                'message': "partner not found",
            }
        )
        return

    detokenize_partner = partnership_detokenize_sync_object_model(
        PiiSource.PARTNER,
        partner,
        customer_xid=None,
        fields_param=['name', 'email'],
        pii_type=PiiVaultDataType.KEY_VALUE,
    )

    target_datetime = timezone.localtime(timezone.now()) - timedelta(hours=1)
    partnership_applications = PartnershipApplicationData.objects.filter(
        application__application_status=ApplicationStatusCodes.LOC_APPROVED,
        partnership_customer_data__partner=partner,
        cdate__lte=target_datetime,
    ).exclude(is_sended_to_email=True)

    if not partnership_applications:
        logger.warning(
            {
                'action_view': 'failed_send_report_new_merchant_to_axiata',
                'message': "no new merchant data",
            }
        )
        return
    try:
        email_client = get_julo_email_client()
        subject = 'Ini Daftar Merchant yang Disetujui'
        template = 'report_mf_axiata_email.html'
        email_from = EMAIL_SENDER_FOR_AXIATA
        target_email = detokenize_partner.email
        footer_image = 'https://julostatics.oss-ap-southeast-5.aliyuncs.com/common/otp/footer.png'

        with transaction.atomic():
            with TempDir(dir="/media") as tempdir:
                file_name, file_path, temp_dir = generate_csv_for_new_merchant(
                    partnership_applications,
                    tempdir
                )
                # Send Email
                context = {
                    'footer_url': 'footer.png',
                    'full_name': detokenize_partner.name.capitalize(),
                    'footer_image': footer_image,
                }
                msg = render_to_string(template, context)

                with open(file_path, "rb") as csvfile:
                    file = csvfile.read()
                    encoded = base64.b64encode(file)
                    attachment_dict = {
                        'content': encoded.decode(),
                        'filename': file_name,
                        'type': 'text/csv'
                    }
                    status, body, headers = email_client.send_email(
                        subject=subject,
                        content=msg,
                        email_to=detokenize_partner.email,
                        email_from=email_from,
                        name_from='JULO',
                        reply_to=email_from,
                        attachment_dict=attachment_dict,
                        content_type="text/html",
                    )

                    EmailHistory.objects.create(
                        status=status,
                        sg_message_id=headers['X-Message-Id'],
                        to_email=target_email,
                        subject=subject,
                        message_content=msg,
                        template_code='report_mf_axiata_email',
                    )
                csvfile.close()
                logger.info(
                    {
                        'action_view': 'successfully_send_report_new_merchant_to_axiata',
                        'message': "success send data to axiata",
                    }
                )
    except ValueError as error:
        raise JuloException(error)


@task(queue='partner_mf_global_queue')
def web_app_send_reset_password_email(email: str, partner: str, reset_password_key: str):
    reset_link = settings.JULO_WEB_URL + '/merchant/{}/reset-password/{}'.format(
        partner,
        reset_password_key
    )
    logger.info(
        {
            'status': 'reset_password_link_created',
            'action': 'sending_email_reset_password_web_app',
            'email': email,
            'reset_password_page_link': reset_link,
        }
    )
    time_now = timezone.localtime(timezone.now()).strftime('%Y-%m-%d %H:%M:%S')
    subject = "JULO: Reset Password (%s) - %s" % (email, time_now)
    template = get_template('email_reset_password_mf_web_app.html')
    username = email.split("@")
    variable = {"link": reset_link, "name": username[0]}
    html_content = template.render(variable)
    status, _, headers = get_julo_email_client().send_email(
        subject, html_content, email, settings.EMAIL_FROM
    )

    message_id = headers['X-Message-Id']
    EmailHistory.objects.create(
        to_email=email,
        subject=subject,
        sg_message_id=message_id,
        template_code='email_reset_password',
        status=str(status),
    )

    customer_password_change_service = password_services.CustomerPinChangeService()
    customer_password_change_service.update_email_status_to_sent(reset_password_key)


@task(queue='partner_mf_global_queue')
def send_list_new_merchant_financing_axiata_csv_upload():
    # Generate CSV
    pii_filter_dict = generate_pii_filter_query_partnership(
        Partner, {'name': PartnerNameConstant.AXIATA_WEB}
    )
    partner = Partner.objects.filter(is_active=True, **pii_filter_dict).last()

    if not partner:
        logger.warning(
            {
                'action_view': 'failed_send_report_new_merchant_csv_upload_to_axiata',
                'message': "partner not found",
            }
        )
        return

    detokenize_partner = partnership_detokenize_sync_object_model(
        PiiSource.PARTNER,
        partner,
        customer_xid=None,
        fields_param=['name', 'email'],
        pii_type=PiiVaultDataType.KEY_VALUE,
    )
    target_datetime = timezone.localtime(timezone.now()) - timedelta(hours=1)
    partnership_applications = PartnershipApplicationData.objects.select_related(
        'application').filter(
        application__application_status=ApplicationStatusCodes.LOC_APPROVED,
        partnership_customer_data__partner=partner,
        cdate__lte=target_datetime,
    ).exclude(is_sended_to_email=True)

    if not partnership_applications:
        logger.warning(
            {
                'action_view': 'failed_send_report_new_merchant_csv_upload_to_axiata',
                'message': "no new merchant data",
            }
        )
        return
    try:
        email_client = get_julo_email_client()
        subject = 'Ini Daftar Merchant yang Disetujui'
        template = 'report_mf_axiata_email.html'
        email_from = EMAIL_SENDER_FOR_AXIATA
        target_email = detokenize_partner.email
        footer_image = 'https://julostatics.oss-ap-southeast-5.aliyuncs.com/common/otp/footer.png'

        with TempDir(dir="/media") as tempdir:
            file_name, file_path, temp_dir = generate_csv_for_new_merchant(
                partnership_applications,
                tempdir
            )
            # Send Email
            context = {
                'footer_url': 'footer.png',
                'full_name': detokenize_partner.name.capitalize(),
                'footer_image': footer_image,
            }
            msg = render_to_string(template, context)

            with open(file_path, "rb") as csvfile:
                file = csvfile.read()
                encoded = base64.b64encode(file)
                attachment_dict = {
                    'content': encoded.decode(),
                    'filename': file_name,
                    'type': 'text/csv'
                }
                status, body, headers = email_client.send_email(
                    subject=subject,
                    content=msg,
                    email_to=detokenize_partner.email,
                    email_from=email_from,
                    name_from='JULO',
                    reply_to=email_from,
                    attachment_dict=attachment_dict,
                    content_type="text/html",
                )

                EmailHistory.objects.create(
                    status=status,
                    sg_message_id=headers['X-Message-Id'],
                    to_email=target_email,
                    subject=subject,
                    message_content=msg,
                    template_code='report_mf_axiata_email',
                )
            csvfile.close()
            logger.info(
                {
                    'action_view': 'successfully_send_report_new_merchant_csv_upload_to_axiata',
                    'message': "success send data to axiata",
                }
            )
    except ValueError as error:
        raise JuloException(error)


@task(queue='partner_mf_global_queue')
def send_success_email_after_loan_220(loan_id: int) -> None:
    loan = (
        Loan.objects.filter(id=loan_id)
        .select_related(
            'loan_status',
            'account__partnership_customer_data',
            'account__partnership_customer_data__partner',
            'account__partnership_customer_data__application',
        )
        .first()
    )
    if not loan:
        logger.info(
            {
                'task': 'send_success_email_after_loan_220',
                'loan_id': loan_id,
                'message': "loan not found",
            }
        )
        return

    if loan.loan_status_id != LoanStatusCodes.CURRENT:
        logger.info(
            {
                'task': 'send_success_email_after_loan_220',
                'loan_id': loan_id,
                'message': "loan status is not {}".format(LoanStatusCodes.CURRENT),
            }
        )
        return

    if not hasattr(loan.account, 'partnership_customer_data'):
        logger.info(
            {
                'task': 'send_success_email_after_loan_220',
                'loan_id': loan_id,
                'message': "loan.account doesn't have partnership_customer_data",
            }
        )
        return

    partnership_customer_data = loan.account.partnership_customer_data
    partner = partnership_customer_data.partner
    partnership_application_data = partnership_customer_data.partnershipapplicationdata_set.last()

    application = partnership_customer_data.application
    detokenize_application = partnership_detokenize_sync_object_model(
        PiiSource.APPLICATION,
        application,
        application.customer.customer_xid,
        ['fullname'],
    )
    borrower_name = detokenize_application.fullname

    detokenize_partnership_customer_data = partnership_detokenize_sync_object_model(
        PiiSource.PARTNERSHIP_CUSTOMER_DATA,
        partnership_customer_data,
        application.customer.customer_xid,
        ['nik'],
    )
    ktp = detokenize_partnership_customer_data.nik

    detokenize_partner = partnership_detokenize_sync_object_model(
        PiiSource.PARTNER,
        partner,
        application.customer.customer_xid,
        fields_param=['email'],
        pii_type=PiiVaultDataType.KEY_VALUE,
    )

    loan_amount = loan.loan_amount
    company_name = partnership_application_data.company_name

    email_client = get_julo_email_client()
    email_from = EMAIL_SENDER_FOR_AXIATA
    subject = 'Julo - Proses Peminjaman {} Berhasil'.format(borrower_name)
    template = 'mf_webapp_success_email_after_220.html'
    context = {
        'borrower_name': borrower_name,
        'ktp': ktp,
        'loan_amount': loan_amount,
        'company_name': company_name,
    }
    content = render_to_string(template, context)

    try:
        status, _, headers = email_client.send_email(
            subject=subject,
            content=content,
            email_to=detokenize_partner.email,
            email_from=email_from,
            name_from='JULO',
            reply_to=email_from,
            content_type="text/html",
        )
        EmailHistory.objects.create(
            status=status,
            sg_message_id=headers['X-Message-Id'],
            to_email=partner.email,
            subject=subject,
            message_content=content,
            template_code='mf_webapp_success_email_after_220',
        )
    except Exception as e:
        logger.info(
            {
                'task': 'send_success_email_after_loan_220',
                'loan_id': loan_id,
                'message': "Exception {}".format(e),
            }
        )
    return


@task(queue='partner_mf_global_queue')
def trigger_update_late_fee_amount_mf_axiata():
    unpaid_payments = (
        Payment.objects.not_paid_active_overdue()
        .filter(loan__account__account_lookup__name=PartnershipAccountLookup.MERCHANT_FINANCING)
        .values_list("id", "account_payment__account__id")
        .order_by('id')
    )

    mapping_account_from_payments = defaultdict(list)
    for payment in unpaid_payments.iterator():
        account_id = payment[1]
        mapping_account_from_payments[account_id].append(payment[0])

    account_id_keys = list(mapping_account_from_payments.keys())
    chunks = [account_id_keys[i: i + 20] for i in range(0, len(account_id_keys), 20)]

    for chunk in chunks:
        chain_tasks = []
        for account_id in chunk:
            payment_ids = mapping_account_from_payments[account_id]
            chain_tasks.append(axiata_update_late_fee_amount_task.si(payment_ids))
        group_tasks = group(chain(*chain_tasks))
        group_tasks()


@task(queue='partner_mf_global_queue')
def axiata_update_late_fee_amount_task(payment_ids: List):
    fn_name = 'axiata_update_late_fee_amount_task'
    logger.info(
        {
            "task": fn_name,
            "state": "Start",
            "action": "process_axiata_late_fee_amount",
            "message": "Process Axiata Late Fee Amount",
            "payment_ids": payment_ids,
        }
    )

    for payment_id in payment_ids:
        axiata_update_late_fee_amount(payment_id)

    logger.info(
        {
            "task": fn_name,
            "state": "Finish",
        }
    )


@task(queue='partner_mf_global_queue')
def process_mf_web_app_merchant_upload_file_task(
    upload_async_state_id: int,
    partner_id: int,
    created_by_user_id: int,
) -> None:
    upload_async_state = UploadAsyncState.objects.filter(
        id=upload_async_state_id,
        task_type=MFWebAppUploadAsyncStateType.MF_STANDARD_PRODUCT_MERCHANT_REGISTRATION,
        task_status=UploadAsyncStateStatus.WAITING,
    ).first()
    if not upload_async_state or not upload_async_state.file:
        logger.info(
            {
                "action": "mf_standard_process_process_merchant_upload_task_failed",
                "message": "File not found",
                "upload_async_state_id": upload_async_state_id,
            }
        )

        if upload_async_state:
            upload_async_state.update_safely(task_status=UploadAsyncStateStatus.FAILED)

        return

    partner = Partner.objects.filter(id=partner_id).last()
    if not partner:
        logger.info(
            {
                "action": "mf_standard_process_process_merchant_upload_task_failed",
                "message": "Partner not found",
                "upload_async_state_id": upload_async_state_id,
            }
        )
        return

    upload_async_state.update_safely(task_status=UploadAsyncStateStatus.PROCESSING)
    try:
        is_success_all = process_merchant_upload(upload_async_state, partner, created_by_user_id)
        if is_success_all:
            task_status = UploadAsyncStateStatus.COMPLETED
        else:
            task_status = UploadAsyncStateStatus.PARTIAL_COMPLETED
        upload_async_state.update_safely(task_status=task_status)

    except Exception as e:
        logger.exception(
            {
                'action': 'mf_standard_process_process_merchant_upload_task_failed',
                'upload_async_state_id': upload_async_state_id,
                'error': e,
            }
        )
        upload_async_state.update_safely(task_status=UploadAsyncStateStatus.FAILED)


@task(queue='partner_mf_global_queue')
def merchant_financing_std_move_status_131_async_process(
    application_id: int, list_of_verification_files: list
) -> None:
    from juloserver.julo.product_lines import ProductLineCodes

    # Feature settings to process move status with asynchronous
    mf_standard_async_config = (
        FeatureSetting.objects.filter(feature_name=MFFeatureSetting.MF_STANDARD_ASYNC_CONFIG)
        .values_list('parameters', flat=True)
        .last()
    )

    if not mf_standard_async_config or (
        mf_standard_async_config
        and not mf_standard_async_config.get(MFFeatureSetting.MF_STANDARD_RESUBMISSION_ASYNC_CONFIG)
    ):
        logger.error(
            {
                "action": "merchant_financing_std_move_status_131_async_process",
                "message": "mf_standard_async_config feature is off",
            }
        )

    new_status_code = ApplicationStatusCodes.APPLICATION_RESUBMISSION_REQUESTED
    try:
        with transaction.atomic():
            allowed_statuses = {
                ApplicationStatusCodes.SCRAPED_DATA_VERIFIED,
                ApplicationStatusCodes.APPLICATION_RESUBMITTED,
            }
            mf_product_line = ProductLineCodes.MERCHANT_FINANCING_STANDARD_PRODUCT
            partnership_application_data = (
                PartnershipApplicationData.objects.select_for_update()
                .select_related('application')
                .filter(
                    application_id=application_id,
                    application__application_status_id__in=allowed_statuses,
                    application__product_line_id=mf_product_line,
                )
                .last()
            )
            if not partnership_application_data:
                logger.error(
                    {
                        'action': 'merchant_financing_std_move_status_131_async_process',
                        'message': 'application not fond',
                        "application_id": application_id,
                        "files": list_of_verification_files,
                    }
                )
                return

            application_id = partnership_application_data.application_id
            process_application_status_change(
                application_id,
                new_status_code,
                change_reason="agent_triggered",
            )
            reject_reason = {'resubmit_document': list_of_verification_files}
            partnership_application_data.reject_reason.update(reject_reason)
            partnership_application_data.save(update_fields=['reject_reason'])
            logger.info(
                {
                    "action": "merchant_financing_std_move_status_131_async_process",
                    "message": "success move status application status to 131",
                    "application_id": application_id,
                }
            )
    except Exception as error:
        logger.error(
            {
                'action': 'merchant_financing_std_move_status_131_async_process',
                'message': 'failed change status',
                'error': str(error),
                'application_id': application_id,
                'files': list_of_verification_files,
            }
        )


@task(queue='partner_mf_global_queue')
def generate_axiata_customer_data_task(loan_id):
    loan = Loan.objects.filter(pk=loan_id).first()
    if not loan:
        logger.error(
            {
                'action': 'generate_axiata_customer_data_task',
                'message': 'loan not found',
                'loan_id': str(loan_id),
            }
        )
        return
    new_axiata_customer_data, err = generate_axiata_customer_data(loan)
    if err:
        logger.error(
            {
                'action': 'generate_axiata_customer_data_task',
                'message': 'error generate_axiata_customer_data',
                'loan_id': str(loan_id),
                'error': str(err),
            }
        )
        return
    new_axiata_customer_data.save()

    axiata_customer_data = AxiataCustomerData.objects.filter(loan_xid=loan.loan_xid).first()
    axiata_customer_data.disbursement_date = None
    axiata_customer_data.disbursement_time = None
    axiata_customer_data.save()


@task(bind=True, name="dukcapil_fr_mf_trigger_task", queue="partner_mf_global_queue", max_retries=3)
def dukcapil_fr_mf_trigger_task(self, application=None, setting=None, is_mfsp_partner=False):
    logger.info(
        {
            'action': 'dukcapil_fr_mf_trigger_task',
            'is_mfsp_partner': is_mfsp_partner,
            'application_id': application.id,
            'message': 'triggering dukcapil fr mf trigger task',
        }
    )
    next_status_code = ApplicationStatusCodes.LOC_APPROVED
    # trigger dukcapil fr mfsp
    if not DukcapilFaceRecognitionCheck.objects.filter(
        application_id=application.id,
        response_code__isnull=False,
    ).exists():
        dukcapil_fr_service = DukcapilFRService(application.id, application.ktp)
        try:
            if is_mfsp_partner:
                dukcapil_fr_service.face_recognition_partnership()
            else:
                dukcapil_fr_service.face_recognition()
        except SelfieImageNotFound:
            note = "User bypassed to 190 due to no selfie image"

            ApplicationNote.objects.create(application_id=application.id, note_text=note)

            process_application_status_change(
                application.id,
                new_status_code=next_status_code,
                change_reason="Success Dukcapil FR validation",
            )
            return
        except Exception:
            if self.request.retries < 3:
                time.sleep(1)
                logger.info(
                    {
                        'action': 'dukcapil_fr_mf_trigger_task',
                        'is_mfsp_partner': is_mfsp_partner,
                        'application_id': application.id,
                        'message': 'retry dukcapil fr mf trigger task',
                    }
                )
                raise self.retry(
                    kwargs={
                        'application': application,
                        'setting': setting,
                    }
                )

    if validate_dukcapil_fr_partnership(application, setting):
        process_application_status_change(
            application.id,
            new_status_code=next_status_code,
            change_reason="Success Dukcapil FR validation",
        )
