import logging
import os
import tempfile
import pytz
import requests
import pdfkit
import uuid
import math

from typing import Dict, Union, Any
from babel.dates import format_datetime
from celery import task
from django.conf import settings
from django.core.exceptions import ObjectDoesNotExist
from django.db import transaction
from django.template import Context, Template
from django.utils import timezone
from xhtml2pdf import pisa
from datetime import datetime, timedelta
from rest_framework import status
from dateutil import parser

from juloserver.account.constants import AccountConstant
from juloserver.account.services.account_related import process_change_account_status
from juloserver.account_payment.models import AccountPayment
from juloserver.account_payment.services.account_payment_history import (
    update_account_payment_status_history,
)
from juloserver.dana.constants import (
    DanaInstallmentType,
    PaymentReferenceStatus,
    AccountUpdateResponseCode,
    DANA_ONBOARDING_FIELD_TO_TRACK,
)

from juloserver.dana.loan.tasks import dana_generate_auto_lender_agreement_document_task
from juloserver.dana.repayment.tasks import account_reactivation
from juloserver.dana.models import DanaLoanReference, DanaPaymentBill, DanaApplicationReference
from juloserver.application_flow.constants import PartnerNameConstant
from juloserver.customer_module.services.customer_related import (
    update_cashback_balance_status,
)
from juloserver.dana.constants import (
    DANA_DEFAULT_TNC_AND_PRIVACY_POLICY_URL,
    DanaDocumentConstant,
    DanaFDCResultStatus,
    DanaEndpointAPI,
    DanaFDCStatusSentRequest,
    DANA_HEADER_X_PARTNER_ID,
    DANA_HEADER_CHANNEL_ID,
)
from juloserver.dana.loan.services import (
    create_or_update_account_payments,
    dana_loan_agreement_template,
    update_commited_amount_for_lender,
)
from juloserver.dana.services import (
    dana_process_recover_airudder_for_manual_upload,
    dana_update_loan_status_and_loan_history,
)

from juloserver.dana.utils import send_to_slack_notification, create_x_signature
from juloserver.dana.models import DanaFDCResult, DanaCustomerData
from juloserver.disbursement.models import Disbursement
from juloserver.fdc.exceptions import FDCServerUnavailableException
from juloserver.fdc.services import get_and_save_fdc_data
from juloserver.julo.clients import get_julo_sentry_client
from juloserver.julo.constants import FeatureNameConst, WorkflowConst
from juloserver.julo.exceptions import JuloException
from juloserver.julo.models import (
    Application,
    Document,
    FeatureSetting,
    Loan,
    Partner,
    Skiptrace,
    CustomerFieldChange,
    FDCInquiry,
    Workflow,
)
from juloserver.julo.product_lines import ProductLineCodes
from juloserver.julo.services import update_is_proven_bad_customers
from juloserver.julo.statuses import LoanStatusCodes, PaymentStatusCodes, ApplicationStatusCodes
from juloserver.julo.utils import (
    format_e164_indo_phone_number,
    post_anaserver,
    execute_after_transaction_safely,
    upload_file_as_bytes_to_oss,
)
from juloserver.minisquad.constants import DialerSystemConst
from juloserver.monitors.notifications import (
    notify_cron_job_has_been_hit_more_than_once,
    notify_dana_loan_stuck_211_payment_consult,
)
from juloserver.partnership.constants import (
    PartnershipImageStatus,
    PartnershipLoanStatusChangeReason,
    PartnershipFlag,
    PartnershipFeatureNameConst,
)
from juloserver.partnership.models import (
    PartnershipImage,
    PartnershipFlowFlag,
    PartnershipFeatureSetting,
)
from juloserver.partnership.utils import (
    idempotency_check_cron_job,
    is_idempotency_check,
    generate_pii_filter_query_partnership,
    partnership_detokenize_sync_object_model,
)
from juloserver.portal.core.templatetags.unit import format_rupiahs
from juloserver.dana.scripts.fill_empty_marital_status_dana import insert_marital_status_dana
from juloserver.dana.scripts.resend_existing_user_registration_to_pusdafil import (
    do_resend_existing_user_registration_to_pusdafil,
)
from juloserver.dana.collection.services import AIRudderPDSServices
from juloserver.pii_vault.constants import PiiSource, PiiVaultDataType

logger = logging.getLogger(__name__)


@task(bind=True, name="upload_dana_customer_image", queue="dana_global_queue", max_retries=3)
def upload_dana_customer_image(
    self, image_url: str, image_type: str, product_type: str, application_id: int
) -> None:
    """
    Url image from dana is valid only 1 Hour,
    If failed We retry this on every one minutes in 3 times
    """

    try:
        from juloserver.partnership.services.services import download_image_byte_from_url

        image_byte = download_image_byte_from_url(image_url)

        partnership_image = PartnershipImage()
        partnership_image.image_type = image_type
        partnership_image.application_image_source = application_id
        partnership_image.product_type = product_type
        partnership_image.save()

        application = (
            Application.objects.filter(id=partnership_image.application_image_source)
            .select_related("customer")
            .first()
        )
        if not application:
            raise JuloException(
                "Application id=%s not found" % partnership_image.application_image_source
            )

        cust_id = str(application.customer.id)
        filename = "%s_%s%s" % (
            partnership_image.image_type,
            str(partnership_image.id),
            '.jpeg',
        )
        image_remote_filepath = "/".join(
            ["cust_" + cust_id, "partnership_image_application", filename]
        )

        upload_file_as_bytes_to_oss(settings.OSS_MEDIA_BUCKET, image_byte, image_remote_filepath)
        partnership_image.url = image_remote_filepath
        partnership_image.save()

        logger.info(
            {
                "status": "successfull dana upload image to s3",
                "image_remote_filepath": image_remote_filepath,
                "application_id": partnership_image.application_image_source,
                "image_type": partnership_image.image_type,
            }
        )

        # mark all other images with same type as 'deleted'
        images = (
            PartnershipImage.objects.exclude(id=partnership_image.id)
            .exclude(image_status=PartnershipImageStatus.INACTIVE)
            .filter(
                application_image_source=partnership_image.application_image_source,
                image_type=partnership_image.image_type,
            )
        )

        for img in images:
            logger.info({"action": "marking_deleted", "image": img.id})
            img.image_status = PartnershipImageStatus.INACTIVE
            img.save()

    except (Exception, JuloException) as exception_error:
        if self.request.retries > self.max_retries:
            error_data = {
                "action": "failed_upload_dana_customer_image",
                "message": "Failed to upload image",
                "type": image_type,
                "application_id": application_id,
                "error": str(exception_error),
            }

            logger.exception(error_data)
            error_msg = "Failed to upload Dana image {}".format(error_data)
            send_to_slack_notification(error_msg)
            raise exception_error

        logger.info(
            {
                "action": "retry_upload_dana_customer_image",
                "message": "Failed to upload image",
                "application_id": application_id,
                "error": str(exception_error),
            }
        )
        raise self.retry(exc=exception_error, countdown=60)


@task(name="generate_dana_application_master_agreement", queue="dana_global_queue")
def generate_dana_application_master_agreement(application_id: int) -> bool:
    from juloserver.dana.onboarding.services import dana_master_agreement_template
    from juloserver.julo.tasks import upload_document

    application = Application.objects.get(pk=application_id)

    if application.product_line_code not in {
        ProductLineCodes.DANA,
        ProductLineCodes.DANA_CASH_LOAN,
    }:
        err_message = 'Application ID: {} not using product line DANA'.format(application_id)
        raise ValueError(err_message)

    try:
        hash_digi_sign = "PPFP-" + str(application.application_xid)
        ma_content = dana_master_agreement_template(application)
        temp_dir = tempfile.gettempdir()
        filename = 'master_agreement-{}.pdf'.format(hash_digi_sign)
        file_path = os.path.join(temp_dir, filename)
        file = open(file_path, "w+b")
        pdf = pisa.CreatePDF(ma_content, dest=file, encoding="UTF-8")
        file.close()

        if pdf.err:
            err_message = 'Failed to create PDF Dana Master Agreement from Application ID: '
            raise ValueError('{}{}'.format(err_message, application_id))

        ma_document = Document.objects.create(
            document_source=application.id,
            document_type='master_agreement',
            filename=filename,
            hash_digi_sign=hash_digi_sign,
            accepted_ts=timezone.localtime(timezone.now()),
            application_xid=application.application_xid,
        )

        logger.info(
            {
                'action_view': 'Master Agreement DANA - generate_application_master_agreement',
                'data': {'application_id': application.id, 'document_id': ma_document.id},
                'message': "success create Dana Master Agreement PDF",
            }
        )

        # TODO-DANA: Need send email or not because dana not send email cutomer

        upload_document(document_id=ma_document.id, local_path=file_path)
    except Exception as e:
        raise JuloException(e)


@task(queue="dana_global_queue")
def update_dana_account_payment_status():
    """
    update account payment status every night
    """

    unpaid_account_payment_ids = (
        AccountPayment.objects.status_tobe_update(is_partner=True)
        .select_related('account')
        .filter(account__application__partner__name=PartnerNameConstant.DANA)
        .values_list("id", flat=True)
    )
    for unpaid_account_payment_id in unpaid_account_payment_ids:
        update_dana_account_payment_status_subtask.delay(unpaid_account_payment_id)


@task(queue="dana_global_queue")
def update_dana_account_payment_status_subtask(account_payment_id):
    with transaction.atomic():
        account_payment = (
            AccountPayment.objects.select_for_update()
            .select_related('account')
            .get(pk=account_payment_id)
        )
        if account_payment.status_id in PaymentStatusCodes.paid_status_codes():
            return
        # Make accounts with x440,441,442 stays  even though they passed the dpd)
        if account_payment.account.status_id in {
            AccountConstant.STATUS_CODE.fraud_reported,
            AccountConstant.STATUS_CODE.application_or_friendly_fraud,
            AccountConstant.STATUS_CODE.scam_victim,
        }:
            return

        new_status_code = account_payment.get_status_based_on_due_date()
        with update_account_payment_status_history(
            account_payment, new_status_code, reason='update_based_on_dpd'
        ):
            account_payment.update_safely(status_id=new_status_code)
            # update account status
            update_dana_account_status_based_on_account_payment(account_payment)

        logger.info(
            {
                "task": "update_dana_account_payment_status_subtask",
                "account_payment id": account_payment.id,
                "new_status_code": new_status_code,
            }
        )


def update_dana_account_status_based_on_account_payment(account_payment, reason_override=''):
    account = account_payment.account
    new_status_code = account_payment.get_status_based_on_due_date()
    dpd = account_payment.dpd
    previous_account_status_code = account.status_id
    # this if for prevent
    # account bring back to active in grace if have more then 1 account payment
    if previous_account_status_code != AccountConstant.STATUS_CODE.suspended:
        new_account_status_code = None
        new_account_reason = ''
        if (
            new_status_code in {PaymentStatusCodes.PAYMENT_1DPD, PaymentStatusCodes.PAYMENT_5DPD}
            and 1 <= dpd <= 5
        ):
            # change status into 421
            new_account_status_code = AccountConstant.STATUS_CODE.active_in_grace
            new_account_reason = 'reach DPD+1 to +5 '
            update_is_proven_bad_customers(account)
        elif (
            PaymentStatusCodes.PAYMENT_5DPD <= new_status_code <= PaymentStatusCodes.PAYMENT_180DPD
        ):
            # change status into 430
            new_account_status_code = AccountConstant.STATUS_CODE.suspended
            new_account_reason = 'reach DPD >+5 ++ '

        if reason_override:
            new_account_reason = reason_override

        if new_account_status_code:
            process_change_account_status(account, new_account_status_code, new_account_reason)
            update_cashback_balance_status(account.customer)


# add retry incase the loan agreement failed
@task(bind=True, queue="dana_loan_agreement_queue", max_retries=3)
def generate_dana_loan_agreement(self, application_id: int, loan_id: int, content: Dict) -> bool:
    """
    If there is change in template agreement,
    need to adjust signature location in this class
    DanaLoanBorrowerSignature & DanaLoanProviderSignature to prevent error
    """
    from juloserver.dana.loan.services import (
        dana_loan_agreement_template,
    )

    from juloserver.disbursement.models import Disbursement
    from juloserver.julo.models import XidLookup
    from juloserver.julo.tasks import upload_document

    application = Application.objects.filter(id=application_id).last()
    loan = Loan.objects.filter(id=loan_id).only("id", "loan_xid").last()

    if not application and not loan:
        err_message = 'Application ID: {} or Loan ID: {} not exists'.format(application_id, loan_id)
        raise ValueError(err_message)

    if not application.application_xid:
        application.application_xid = XidLookup.get_new_xid()
        application.save(update_fields=['application_xid'])

        disbursement = Disbursement.objects.filter(external_id=loan_id).last()

        if not disbursement:
            raise JuloException("Disbursement not found with loan_id: {}".format(loan_id))

        disbursement.external_id = application.application_xid
        disbursement.save(update_fields=['external_id'])
        disbursement.create_history('update', ['external_id'])

    if (
        application.product_line_code != ProductLineCodes.DANA
        and application.product_line_code != ProductLineCodes.DANA_CASH_LOAN
    ):
        err_message = 'Application ID: {} not using product line DANA'.format(application_id)
        raise ValueError(err_message)

    try:
        contract_number = "PPFP-" + str(application.application_xid) + "-" + str(loan.loan_xid)
        ma_content = dana_loan_agreement_template(application.application_xid, loan, content)
        temp_dir = tempfile.gettempdir()
        filename = 'dana-loan-agreement-{}.pdf'.format(contract_number)
        file_path = os.path.join(temp_dir, filename)
        pdfkit.from_string(ma_content, file_path)
        file = open(file_path, "rb")
        file.close()

        ma_document = Document.objects.create(
            document_source=loan.id,
            document_type=DanaDocumentConstant.LOAN_AGREEMENT_TYPE,
            filename=filename,
            application_xid=application.application_xid,
            loan_xid=loan.loan_xid,
            service=DanaDocumentConstant.DOCUMENT_SERVICE,
        )
        upload_document(document_id=ma_document.id, local_path=file_path, is_loan=True)
    except Exception as e:
        if self.request.retries < self.max_retries:
            interval = 3600 * (self.request.retries + 1)
            logger.info(
                {
                    "action": "generate_dana_loan_agreement",
                    'loan_id': loan_id,
                    'data': {'error': str(e)},
                    "message": "Retry to create dana loan agreement",
                }
            )
            raise self.retry(exc=e, countdown=interval)

        logger.error(
            {
                'action_view': 'generate_dana_loan_agreement',
                'loan_id': loan_id,
                'data': {'error': str(e)},
                'message': "fail create dana_loan_agreement PDF",
            }
        )
        raise JuloException(e)


@task(queue="dana_transaction_queue")
def dana_lender_auto_approval_task(loan_id):
    loan = Loan.objects.get_or_none(pk=loan_id)
    if not loan:
        raise JuloException(
            {
                'action': 'dana_lender_auto_approval_task',
                'message': 'Loan ID not found!!',
                'loan_id': loan_id,
            }
        )

    # make sure this function was called just for loan status is 211
    if loan.status not in {LoanStatusCodes.LENDER_APPROVAL, LoanStatusCodes.FUND_DISBURSAL_ONGOING}:
        logger.info(
            {
                'action': 'dana_lender_auto_approval_task',
                'loan_id': loan.id,
                'message': 'loan status is not in ({}, {}) current loan status is {}'.format(
                    LoanStatusCodes.LENDER_APPROVAL,
                    LoanStatusCodes.FUND_DISBURSAL_ONGOING,
                    loan.status,
                ),
            }
        )
        return

    dana_lender_auto_approve = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.DANA_LENDER_AUTO_APPROVE, is_active=True
    ).first()

    is_payment_consult_loan = (
        hasattr(loan, 'danaloanreference') and loan.danaloanreference.is_whitelisted
    )
    if dana_lender_auto_approve or is_payment_consult_loan:
        dana_generate_auto_lender_agreement_document_task.delay(loan.id)

        update_loan_to_212 = True
        if is_payment_consult_loan:
            # Need to check this to decide this payment consult
            # In payment consult loan 212 happen in lender dashboard
            update_loan_to_212 = False

        logger.info(
            {
                'action': 'dana_lender_auto_approval_task',
                'loan_id': loan_id,
                'status': loan.status,
                'account_id': loan.account_id,
                'update_loan_to_212': update_loan_to_212,
                'message': 'running dana_disbursement_trigger_task',
            }
        )

        dana_disbursement_trigger_task.delay(loan.id, update_loan_to_212)


@task(queue="dana_transaction_queue")
def dana_disbursement_trigger_task(loan_id, update_loan_to_212: bool = True):
    from juloserver.dana.repayment.services import resume_dana_repayment

    loan = Loan.objects.get_or_none(pk=loan_id)
    if not loan:
        raise JuloException(
            {
                'action': 'dana_disbursement_trigger_task',
                'message': 'Loan ID not found!!',
                'loan_id': loan_id,
            }
        )

    logger.info(
        {
            'action': 'dana_disbursement_trigger_task',
            'loan_id': loan_id,
            'update_loan_to_212': update_loan_to_212,
            'status': loan.status,
            'message': 'start dana_disbursement_trigger_task',
        }
    )

    application = Application.objects.filter(id=loan.application_id2).last()
    if not application:
        raise JuloException(
            {
                'action': 'dana_disbursement_trigger_task',
                'message': 'Application not found!!',
                'loan_id': loan_id,
            }
        )

    pii_filter_dict = generate_pii_filter_query_partnership(
        Partner, {'name': PartnerNameConstant.DANA}
    )
    partner = Partner.objects.filter(is_active=True, **pii_filter_dict).last()
    detokenize_partner = partnership_detokenize_sync_object_model(
        PiiSource.PARTNER,
        partner,
        customer_xid=None,
        fields_param=['name', 'email'],
        pii_type=PiiVaultDataType.KEY_VALUE,
    )
    partner_loan_request = loan.partnerloanrequest_set.last()
    if not partner_loan_request and partner_loan_request.partner != partner:
        raise JuloException(
            {
                'action': 'dana_disbursement_trigger_task',
                'message': 'Loan Partner is not Dana!!',
                'loan_id': loan_id,
            }
        )

    disbursement = Disbursement.objects.filter(id=loan.disbursement_id).last()
    try:
        with transaction.atomic():
            old_status = loan.status
            # Task should be already 212 on this step
            update_commited_amount_for_lender(
                loan,
                loan.lender,
                disbursement,
                update_loan_status=update_loan_to_212,
            )
            loan.refresh_from_db()
            logger.info(
                {
                    'action': 'dana_disbursement_trigger_task',
                    'loan_id': loan_id,
                    'account_id': loan.account_id,
                    'status': 'move to 212',
                    'old_status': old_status,
                    'new_status': loan.status,
                }
            )
            old_status = loan.status
            dana_update_loan_status_and_loan_history(
                loan.id,
                new_status_code=LoanStatusCodes.CURRENT,
                change_reason=PartnershipLoanStatusChangeReason.ACTIVATED,
            )
            loan.refresh_from_db()
            logger.info(
                {
                    'action': 'dana_disbursement_trigger_task',
                    'loan_id': loan_id,
                    'account_id': loan.account_id,
                    'status': 'move to 220, and creating account payment',
                    'old_status': old_status,
                    'new_status': loan.status,
                }
            )
            payments = loan.payment_set.all()
            payment_ids = payments.values_list('id', flat=True)
            dana_payment_bills = DanaPaymentBill.objects.filter(payment_id__in=set(payment_ids))

            payment_bill_mapping = {bill.payment_id: bill for bill in dana_payment_bills}

            create_or_update_account_payments(payments, loan.account)
            logger.info(
                {
                    'action': 'dana_disbursement_trigger_task',
                    'loan_id': loan_id,
                    'account_id': loan.account_id,
                    'status': 'finished moved loan status and creating account payment',
                }
            )
    except Exception as e:
        logger.info(
            {
                'action': 'dana_disbursement_trigger_task',
                'loan_id': loan_id,
                'account_id': application.account_id,
                'message': 'failed on loan disbursement process error : {}'.format(e),
            }
        )
        raise JuloException(
            {
                'action': 'dana_disbursement_trigger_task',
                'message': e,
                'loan_id': loan_id,
            }
        )

    dana_customer_data = loan.account.dana_customer_data
    detokenize_dana_customer_data = partnership_detokenize_sync_object_model(
        PiiSource.DANA_CUSTOMER_DATA,
        dana_customer_data,
        dana_customer_data.customer.customer_xid,
        ['mobile_number', 'nik', 'full_name'],
    )

    dana_loan_reference = loan.danaloanreference
    transaction_time = dana_loan_reference.trans_time
    provision_amount = format_rupiahs(str(dana_loan_reference.provision_fee_amount), "no_currency")
    late_fee_rate = dana_loan_reference.late_fee_rate

    partner_email = dana_loan_reference.partner_email
    if not partner_email:
        partner_email = detokenize_partner.email
    partner_tnc = dana_loan_reference.partner_tnc
    if not partner_tnc:
        partner_tnc = DANA_DEFAULT_TNC_AND_PRIVACY_POLICY_URL
    partner_privacy_rule = dana_loan_reference.partner_privacy_rule
    if not partner_privacy_rule:
        partner_privacy_rule = DANA_DEFAULT_TNC_AND_PRIVACY_POLICY_URL

    sorted_bills = dict()
    total_interest_amount = 0
    for payment in payments:
        sorted_bills[str(payment.payment_number)] = {}
        dana_payment_bill = payment_bill_mapping.get(payment.id)
        sorted_bills[str(payment.payment_number)]["payment_amount"] = format_rupiahs(
            dana_payment_bill.total_amount, "no"
        )
        sorted_bills[str(payment.payment_number)]["due_date"] = format_datetime(
            dana_payment_bill.due_date, "d MMMM yyyy", locale='id_ID'
        )
        total_interest_amount += float(dana_payment_bill.interest_fee_amount)

    sorted_bills = dict(sorted(sorted_bills.items(), key=lambda x: int(x[0])))

    # update this logic below when Dana have sent installmentType on SF file loan upload :
    # noted on (5 Feb 2025)
    # last installment due_date from payments
    last_installment_due_date = (
        payments.order_by('-due_date').values_list('due_date', flat=True).first()
    )
    loan_created_date = loan.cdate

    installment_type = None
    installment_count = 0
    dana_installment_count = 0
    dana_installment_type = ""
    if dana_loan_reference.installment_config:
        dana_installment_count = dana_loan_reference.installment_config.get('installmentCount', 0)
        dana_installment_type = dana_loan_reference.installment_config.get('installmentType')
        installment_count = int(dana_installment_count)

    if not installment_count:
        last_installment_due_date = datetime.combine(
            last_installment_due_date, datetime.min.time(), tzinfo=loan_created_date.tzinfo
        )
        day_difference = (last_installment_due_date.date() - loan_created_date.date()).days
        installment_count = math.ceil(day_difference / 7)

    if dana_installment_type == DanaInstallmentType.WEEKLY:
        installment_type = "Minggu"
    elif dana_installment_type == DanaInstallmentType.BIWEEKLY:
        installment_type = "Minggu"
        installment_count = int(dana_installment_count) * 2
    elif dana_installment_type == DanaInstallmentType.MONTHLY:
        installment_type = "Bulan"

    content = {
        "date_today": format_datetime(transaction_time, "d MMMM yyyy", locale='id_ID'),
        "customer_name": detokenize_dana_customer_data.full_name,
        "dob": format_datetime(dana_customer_data.dob, "d MMMM yyyy", locale='id_ID'),
        "customer_nik": detokenize_dana_customer_data.nik,
        "customer_phone": detokenize_dana_customer_data.mobile_number,
        "full_address": dana_customer_data.address,
        "partner_email": partner_email,
        "partner_tnc": partner_tnc,
        "partner_privacy_rule": partner_privacy_rule,
        "loan_amount": format_rupiahs(loan.loan_disbursement_amount, "no_currency"),
        "provision_fee_amount": provision_amount,
        "interest_amount": format_rupiahs(total_interest_amount, "no_currency"),
        "late_fee_rate": late_fee_rate,
        "maximum_late_fee_amount": format_rupiahs(loan.loan_disbursement_amount, "no_currency"),
        "installment_count": installment_count,
        "installment_type": installment_type,
    }

    # this one for dana cashloan with dinamic installment table
    installment_table_template = (
        '<table style="width:100%;">'
        '<tbody>'
        '<tr>'
        '<td style="text-align:center"><strong>Cicilan</strong></td>'
        '<td><p><strong>Jumlah</strong></p></td>'
        '<td><p><strong>Jatuh Tempo</strong></p></td>'
        '</tr>'
        '{% for payment_number, payment_data in sorted_bills.items %}'
        '<tr>'
        '<td><p style="text-align:center">{{ payment_number }}</p></td>'
        '<td><p>{{ payment_data.payment_amount }}</p></td>'
        '<td><p>{{ payment_data.due_date }}</p></td>'
        '</tr>'
        '{% endfor %}'
        '</tbody>'
        '</table>'
    )

    installment_table_template = Template(installment_table_template)
    installment_table = installment_table_template.render(Context({'sorted_bills': sorted_bills}))

    content.update({"installment_table": installment_table})

    generate_dana_loan_agreement.delay(application.id, loan.id, content)

    # Resume all repayment pending
    resume_dana_repayment(loan_id=loan_id)


@task(bind=True, name="generate_dana_skiptrace", queue="dana_global_queue", max_retries=3)
def generate_dana_skiptrace_task(self, application_id: int) -> None:
    application = Application.objects.get(id=application_id)
    dana_customer_data = application.dana_customer_data

    try:
        skiptrace = Skiptrace.objects.filter(
            phone_number=format_e164_indo_phone_number(dana_customer_data.mobile_number),
            customer_id=dana_customer_data.customer,
        ).exists()

        if not skiptrace:
            Skiptrace.objects.create(
                contact_name=dana_customer_data.full_name,
                customer=dana_customer_data.customer,
                application=application,
                phone_number=format_e164_indo_phone_number(dana_customer_data.mobile_number),
            )

    except (Exception, JuloException) as exception_error:
        if self.request.retries > self.max_retries:
            error_data = {
                "action": "generate_dana_skiptrace",
                "message": "Failed Generate dana skiptrace",
                "application_id": application.id,
                "error": str(exception_error),
            }

            logger.exception(error_data)
            error_msg = "Failed to upload Dana image {}".format(error_data)
            send_to_slack_notification(error_msg)
            raise exception_error

        logger.info(
            {
                "action": "retry_generate_dana_skiptrace",
                "message": "Failed Generate dana skiptrace",
                "application_id": application.id,
                "error": str(exception_error),
            }
        )
        raise self.retry(exc=exception_error, countdown=60)


def get_dana_loan_agreement_template(
    loan: Loan, lender_sign: bool = False, only_content: bool = False
) -> Any:
    application = Application.objects.filter(id=loan.application_id2).last()
    if not application:
        err_message = 'Application ID: {} not exists'.format(loan.application_id2)
        raise ValueError(err_message)

    dana_customer_data = loan.account.dana_customer_data
    detokenize_dana_customer_data = partnership_detokenize_sync_object_model(
        PiiSource.DANA_CUSTOMER_DATA,
        dana_customer_data,
        dana_customer_data.customer.customer_xid,
        ['mobile_number', 'nik', 'full_name'],
    )
    dana_loan_reference = loan.danaloanreference
    transaction_time = dana_loan_reference.trans_time
    provision_amount = format_rupiahs(str(dana_loan_reference.provision_fee_amount), "no_currency")
    late_fee_rate = dana_loan_reference.late_fee_rate

    pii_filter_dict = generate_pii_filter_query_partnership(
        Partner, {'name': PartnerNameConstant.DANA}
    )
    partner = Partner.objects.filter(is_active=True, **pii_filter_dict).last()
    detokenize_partner = partnership_detokenize_sync_object_model(
        PiiSource.PARTNER,
        partner,
        customer_xid=None,
        fields_param=['name', 'email'],
        pii_type=PiiVaultDataType.KEY_VALUE,
    )
    partner_email = dana_loan_reference.partner_email
    if not partner_email:
        partner_email = detokenize_partner.email
    partner_tnc = dana_loan_reference.partner_tnc
    if not partner_tnc:
        partner_tnc = DANA_DEFAULT_TNC_AND_PRIVACY_POLICY_URL
    partner_privacy_rule = dana_loan_reference.partner_privacy_rule
    if not partner_privacy_rule:
        partner_privacy_rule = DANA_DEFAULT_TNC_AND_PRIVACY_POLICY_URL

    payments = loan.payment_set.all()
    payment_ids = payments.values_list('id', flat=True)
    dana_payment_bills = DanaPaymentBill.objects.filter(payment_id__in=set(payment_ids))

    payment_bill_mapping = {bill.payment_id: bill for bill in dana_payment_bills}

    sorted_bills = dict()
    total_interest_amount = 0

    # last installment due_date from payments
    last_installment_due_date = (
        payments.order_by('-due_date').values_list('due_date', flat=True).first()
    )
    loan_created_date = loan.cdate

    for payment in payments:
        sorted_bills[str(payment.payment_number)] = {}
        dana_payment_bill = payment_bill_mapping.get(payment.id)
        sorted_bills[str(payment.payment_number)]["payment_amount"] = format_rupiahs(
            dana_payment_bill.total_amount, "no"
        )
        sorted_bills[str(payment.payment_number)]["due_date"] = format_datetime(
            dana_payment_bill.due_date, "d MMMM yyyy", locale='id_ID'
        )
        total_interest_amount += float(dana_payment_bill.interest_fee_amount)

    sorted_bills = dict(sorted(sorted_bills.items(), key=lambda x: int(x[0])))

    installment_type = None
    installment_count = 0
    dana_installment_count = 0
    dana_installment_type = ""
    if dana_loan_reference.installment_config:
        dana_installment_count = dana_loan_reference.installment_config.get('installmentCount', 0)
        dana_installment_type = dana_loan_reference.installment_config.get('installmentType')
        installment_count = int(dana_installment_count)

    # update this logic below when Dana have sent installmentType on SF file loan upload :
    # noted on (5 Feb 2025)
    if not installment_count:
        last_installment_due_date = datetime.combine(
            last_installment_due_date, datetime.min.time(), tzinfo=loan_created_date.tzinfo
        )
        day_difference = (last_installment_due_date.date() - loan_created_date.date()).days
        installment_count = math.ceil(day_difference / 7)

    if dana_installment_type == DanaInstallmentType.WEEKLY:
        installment_type = "Minggu"
    elif dana_installment_type == DanaInstallmentType.BIWEEKLY:
        installment_type = "Minggu"
        installment_count = int(dana_installment_count) * 2
    elif dana_installment_type == DanaInstallmentType.MONTHLY:
        installment_type = "Bulan"

    content = {
        "date_today": format_datetime(transaction_time, "d MMMM yyyy", locale='id_ID'),
        "customer_name": detokenize_dana_customer_data.full_name,
        "dob": format_datetime(dana_customer_data.dob, "d MMMM yyyy", locale='id_ID'),
        "customer_nik": detokenize_dana_customer_data.nik,
        "customer_phone": detokenize_dana_customer_data.mobile_number,
        "full_address": dana_customer_data.address,
        "partner_email": partner_email,
        "partner_tnc": partner_tnc,
        "partner_privacy_rule": partner_privacy_rule,
        "loan_amount": format_rupiahs(loan.loan_disbursement_amount, "no_currency"),
        "provision_fee_amount": provision_amount,
        "interest_amount": format_rupiahs(total_interest_amount, "no_currency"),
        "late_fee_rate": late_fee_rate,
        "maximum_late_fee_amount": format_rupiahs(loan.loan_disbursement_amount, "no_currency"),
        "installment_count": installment_count,
        "installment_type": installment_type,
    }

    # this one for dana cashloan with dinamic installment table
    installment_table_template = (
        '<table style="width:100%;">'
        '<tbody>'
        '<tr>'
        '<td style="text-align:center"><strong>Cicilan</strong></td>'
        '<td><p><strong>Jumlah</strong></p></td>'
        '<td><p><strong>Jatuh Tempo</strong></p></td>'
        '</tr>'
        '{% for payment_number, payment_data in sorted_bills.items %}'
        '<tr>'
        '<td><p style="text-align:center">{{ payment_number }}</p></td>'
        '<td><p>{{ payment_data.payment_amount }}</p></td>'
        '<td><p>{{ payment_data.due_date }}</p></td>'
        '</tr>'
        '{% endfor %}'
        '</tbody>'
        '</table>'
    )

    installment_table_template = Template(installment_table_template)
    installment_table = installment_table_template.render(Context({'sorted_bills': sorted_bills}))

    content.update({"installment_table": installment_table})

    if only_content:
        return content
    ma_content = dana_loan_agreement_template(
        application.application_xid, loan, content, lender_sign
    )
    return ma_content


@task(queue='dana_global_queue')
def resend_existing_user_registration_to_pusdafil_task(user_id, application_id):
    application = Application.objects.filter(id=application_id).last()

    # Do not send data to pusdafil if the data is not complete
    # only for Dana Application
    if application and application.is_dana_flow():
        if (
            application.address_provinsi
            and application.address_kabupaten
            and application.address_kodepos
            and application.gender
            and application.job_type
            and application.job_industry
            and application.monthly_income
            and application.marital_status
        ):
            do_resend_existing_user_registration_to_pusdafil(user_id)
        else:
            return


@task(queue="dana_global_queue")
def fill_empty_marital_status_dana() -> None:
    insert_marital_status_dana()

    return


@task(queue='dana_callback_fdc_status_queue')
def process_dana_fdc_result(application_id: int) -> Union[DanaFDCResult, None]:
    from juloserver.dana.onboarding.services import (
        update_dana_fdc_result,
        generate_dana_credit_score_based_fdc_result,
        proces_max_creditor_check,
    )
    from juloserver.partnership.services.services import partnership_mock_get_and_save_fdc_data

    # Retry Config
    feature_setting = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.DANA_FDC_RESULT_RETRY_CONFIGURATION,
        is_active=True,
    ).last()

    if not feature_setting or not feature_setting.parameters.get('retry_policy'):
        logger.error(
            {
                "action": "failed_dana_send_fdc_status",
                "message": "feature is off",
            }
        )
        return

    dana_fdc_result = None
    partner_id = None

    # Process to getting a result from FDC Bureau Data
    with transaction.atomic(using='bureau_db'):
        dana_fdc_result = (
            DanaFDCResult.objects.select_for_update().filter(application_id=application_id).last()
        )

        if not dana_fdc_result:
            logger.error(
                {
                    "application_id": application_id,
                    "action": "failed_getting_fdc_result",
                    "message": "application not have data dana_fdc_result",
                }
            )
            return

        dana_customer_data = DanaCustomerData.objects.filter(
            dana_customer_identifier=dana_fdc_result.dana_customer_identifier,
            lender_product_id=dana_fdc_result.lender_product_id,
        ).last()

        if not dana_customer_data:
            logger.error(
                {
                    "application_id": application_id,
                    "action": "failed_getting_fdc_result",
                    "message": "dana_customer_data not found",
                }
            )
            return

        dana_customer_identifier = dana_customer_data.dana_customer_identifier
        customer_id = dana_customer_data.customer_id
        partner_id = dana_customer_data.partner.id

        if dana_fdc_result.status in (
            DanaFDCStatusSentRequest.SUCCESS,
            DanaFDCStatusSentRequest.PROCESS,
        ):
            logger.error(
                {
                    "action": "dana_send_fdc_status_already_send_or_in_process",
                    "message": "please wait and re check the dana_fdc_result.status",
                    "dana_customer_identifier": dana_customer_identifier,
                    "application_id": application_id,
                    "status": dana_fdc_result.status,
                }
            )
            return

        partner_fdc_mock_feature = FeatureSetting.objects.filter(
            feature_name=FeatureNameConst.PARTNERSHIP_FDC_MOCK_RESPONSE_SET,
            is_active=True,
        ).exists()
        if settings.ENVIRONMENT != 'prod' and partner_fdc_mock_feature:
            fdc_inquiry = dana_customer_data.application.fdcinquiry_set.values('id', 'nik').first()
            mock_fdc = partnership_mock_get_and_save_fdc_data(fdc_inquiry)
            if not mock_fdc:
                logger.warning(
                    {
                        "action": "failed_set_mock_dana_fdc_status",
                        "message": "Dana set mock fdc status failed to Update",
                        "customer_id": dana_customer_identifier,
                        "application_id": application_id,
                        "fdc_inquiry": fdc_inquiry['id'],
                    }
                )
                return
            logger.info(
                {
                    "action": "success_set_mock_dana_fdc_status",
                    "message": "Dana set mock fdc status success to Update",
                    "customer_id": dana_customer_identifier,
                    "application_id": application_id,
                    "fdc_inquiry": fdc_inquiry['id'],
                }
            )

        success_update_fdc = False

        # Run to update fdc status, this run if status fdc is init
        if dana_fdc_result.fdc_status == DanaFDCResultStatus.INIT:
            logger.info(
                {
                    'action': 'process_dana_fdc_result',
                    'dana_customer_identifier': dana_customer_identifier,
                    'application_id': dana_customer_data.application_id,
                    'dana_fdc_status': dana_fdc_result.fdc_status,
                    'status': dana_fdc_result.status,
                    'message': 'update dana fdc result',
                }
            )
            success_update_fdc = update_dana_fdc_result(
                dana_customer_identifier=dana_customer_identifier,
                customer_id=customer_id,
                dana_fdc_result=dana_fdc_result,
                partner_id=partner_id,
            )

        # update and re-fetch data from database
        dana_fdc_result.refresh_from_db()

        if success_update_fdc and dana_fdc_result.fdc_status != DanaFDCResultStatus.INIT:
            logger.info(
                {
                    'action': 'process_dana_fdc_result',
                    'dana_customer_identifier': dana_customer_identifier,
                    'application_id': dana_customer_data.application_id,
                    'dana_fdc_status': dana_fdc_result.fdc_status,
                    'status': dana_fdc_result.status,
                    'is_success_update_fdc': success_update_fdc,
                    'message': 'start generate_pgood_dana_applications',
                }
            )

            # Hit ANA API to generate pgood for DANA applications
            execute_after_transaction_safely(
                lambda: generate_pgood_dana_applications.delay(application_id)
            )

            execute_after_transaction_safely(
                # proces credit_score application generation, in this proces fdc is already created
                lambda: generate_dana_credit_score_based_fdc_result(
                    dana_customer_data.application,
                    dana_fdc_result.fdc_status,
                )
            )

            # Process max 3 creditor check
            execute_after_transaction_safely(
                lambda: proces_max_creditor_check(
                    dana_customer_data.application,
                    dana_fdc_result.fdc_status,
                )
            )

        # Creditor check config
        creditor_check_config = (
            PartnershipFlowFlag.objects.filter(
                partner_id=partner_id, name=PartnershipFlag.MAX_CREDITOR_CHECK
            )
            .values_list('configs', flat=True)
            .last()
        )

        if creditor_check_config and creditor_check_config.get('is_active'):
            application = dana_customer_data.application

            failed_application_status = {
                ApplicationStatusCodes.APPLICATION_FLAGGED_FOR_FRAUD,
                ApplicationStatusCodes.APPLICATION_DENIED,
            }

            # Set the status cancel because on P2P check user not hit account inquiry
            if application.application_status_id in failed_application_status:
                dana_fdc_result.update_safely(status=DanaFDCStatusSentRequest.CANCEL)

            return

    # Process to notify DANA
    # P2P Check flow, if P2P(MAX_CREDITOR_CHECK) enable
    # will send on account inquiry if not continue as usual
    custom_queue = feature_setting.parameters.get('custom_queue')
    countdown = None

    count_down_config_data = (
        PartnershipFlowFlag.objects.filter(
            partner_id=partner_id, name=PartnershipFlag.DANA_COUNTDOWN_PROCESS_NOTIFY_CONFIG
        )
        .values_list('configs', flat=True)
        .last()
    )

    if count_down_config_data and count_down_config_data.get('countdown'):
        countdown = count_down_config_data.get('countdown')
        logger.info(
            {
                "action": "process_dana_fdc_result",
                "application_id": application_id,
                "message": "start countdown {} process to notify DANA".format(countdown),
            }
        )

    if custom_queue and countdown:
        process_sending_dana_fdc_result.apply_async(
            (application_id,), queue=custom_queue, countdown=countdown
        )
    elif custom_queue:
        process_sending_dana_fdc_result.apply_async((application_id,), queue=custom_queue)
    elif countdown:
        process_sending_dana_fdc_result.apply_async((application_id,), countdown=countdown)
    else:
        process_sending_dana_fdc_result.apply_async(
            (application_id,),
        )


@task(queue='dana_callback_fdc_status_queue')
def resend_dana_fdc_result() -> None:
    limit = 1000

    # Resend Config
    feature_setting = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.DANA_FDC_RESULT_RETRY_CONFIGURATION,
        is_active=True,
    ).last()

    if not feature_setting:
        logger.error(
            {
                "action": "resend_dana_fdc_result",
                "message": "feature is off",
            }
        )
        return
    else:
        limit = feature_setting.parameters.get('limit', 1000)

    dana_fdc_pending_list = (
        DanaFDCResult.objects.filter(status=DanaFDCStatusSentRequest.PENDING)
        .values_list('application_id', flat=True)
        .order_by('cdate')
        .all()[:limit]
    )

    for application_id in dana_fdc_pending_list.iterator():
        process_sending_dana_fdc_result.delay(application_id)

    logger.info(
        {
            "action": "resend_dana_fdc_result",
            "message": "Resend {} dana fdc pending status".format(dana_fdc_pending_list.count()),
        }
    )


# this scheduler just work for dana notify flow
@task(queue='dana_transaction_queue')
def trigger_resume_dana_loan_stuck_211():
    fn_name = 'trigger_resume_dana_loan_stuck_211'
    current_time = timezone.localtime(timezone.now())
    check_time = current_time - timedelta(hours=1)
    end_time = check_time - timedelta(hours=1)

    feature_setting_name = PartnershipFeatureNameConst.TRIGGER_RESUME_DANA_LOAN_STUCK_211
    fs = PartnershipFeatureSetting.objects.filter(
        feature_name=feature_setting_name, is_active=True
    ).first()
    if fs:
        stop_on_date = fs.parameters.get('stop_on_date')
        if stop_on_date and current_time.day in stop_on_date:
            logger.info(
                {
                    'function_name': fn_name,
                    'stop_on_date': stop_on_date,
                    'message': 'skip run this task today {}'.format(current_time),
                }
            )
            return
    else:
        logger.info(
            {
                'function_name': fn_name,
                'feature_setting_name': feature_setting_name,
                'message': 'feature setting is not active',
            }
        )
        return

    dana_loan_ref_list = DanaLoanReference.objects.select_related('loan').filter(
        loan__loan_status=LoanStatusCodes.LENDER_APPROVAL,
        cdate__lt=check_time,
        cdate__gte=end_time,
        dana_loan_status__status=PaymentReferenceStatus.SUCCESS,
        is_whitelisted=False,
    )

    if not dana_loan_ref_list:
        return

    logger.info(
        {
            'function_name': fn_name,
            'loan_id': dana_loan_ref_list.values_list('loan_id', flat=True),
            'message': 'resuming dana loan stuck at {}'.format(current_time),
        }
    )

    for loan_ref in dana_loan_ref_list:
        loan = loan_ref.loan
        try:
            dana_lender_auto_approval_task.delay(loan.id)
            account_reactivation.delay(loan.account_id)
        except Exception as e:
            logger.info({'function_name': fn_name, 'status': 'Error', 'error_message': str(e)})


@task(queue='dana_loan_agreement_queue')
def auto_generate_dana_loan_agreement():
    fn_name = 'auto_generate_dana_loan_agreement'
    today = timezone.localtime(timezone.now()).date()
    check_date = today - timedelta(days=1)
    end_date = check_date - timedelta(days=1)
    logger.info(
        {
            "action": fn_name,
            "message": "running auto generate on {}".format(today),
        }
    )

    if is_idempotency_check():
        is_executed = idempotency_check_cron_job(fn_name)
        if is_executed:
            notify_cron_job_has_been_hit_more_than_once(fn_name)
            return

    """
    check for time range within 1 day
    if the scheduler run on 1 febuary 2024
    it will check 30 january 2024 - 31 january 2024
    because there was a possibility that on 1 february
    the task is still running on that day
    """
    logger.info(
        {
            "action": fn_name,
            "message": "start on {}".format(today),
        }
    )
    loan_xids = list(
        DanaLoanReference.objects.select_related('loan')
        .filter(
            loan__loan_status_id__gte=220,
            loan__cdate__lte=check_date,
            loan__cdate__gte=end_date,
        )
        .values_list('loan__loan_xid', flat=True)
    )
    if not loan_xids:
        logger.info(
            {
                "action": "auto_generate_dana_loan_agreement",
                "message": "loan agreement is generated on {}".format(today),
            }
        )
        return

    existed_document_loan_xids = list(
        Document.objects.filter(loan_xid__in=loan_xids)
        .values_list('loan_xid', flat=True)
        .distinct('loan_xid')
    )
    for selected_loan_xid in existed_document_loan_xids:
        loan_xids.remove(selected_loan_xid)

    logger.info(
        {
            "action": fn_name,
            "message": "number of loan agreement that need to be generate {}".format(
                len(loan_xids)
            ),
        }
    )

    for loan_xid in loan_xids:
        manual_generate_loan_agreement(loan_xid)


def manual_generate_loan_agreement(loan_xid):
    with transaction.atomic():
        loan = Loan.objects.get_or_none(loan_xid=loan_xid)
        if not loan:
            err_message = 'loan does not exist'
            raise ValueError(err_message)
        application = Application.objects.get_or_none(id=loan.application_id2)
        if not application:
            err_message = 'application does not exist'
            raise ValueError(err_message)

        content = get_dana_loan_agreement_template(loan, True, only_content=True)

        generate_dana_loan_agreement.delay(application.id, loan.id, content)


@task(queue="dana_global_queue")
def check_dana_loan_stuck_211_payment_consult_flow() -> None:
    if FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.DANA_BLOCK_LOAN_STUCK_211_PAYMENT_CONSULT_TRAFFIC,
        is_active=True,
    ).exists():
        return

    current_time_minus_20s = timezone.now() - timezone.timedelta(seconds=20)
    total_dana_loan_stuck_211 = Loan.objects.filter(
        loan_status=211,
        cdate__lt=current_time_minus_20s,
        danaloanreference__is_whitelisted=True,
    ).count()

    if total_dana_loan_stuck_211 > 0:
        notify_dana_loan_stuck_211_payment_consult(total_dana_loan_stuck_211)


@task(bind=True, name="process_complete_application_data", queue="dana_global_queue", max_retries=3)
def process_completed_application_data_task(self, application_id: int) -> None:
    from juloserver.dana.onboarding.services import process_completed_application_data

    try:
        logger.info(
            {
                "action": "start_process_completed_application_data_task",
                "message": "start running process_completed_application_data",
                "application_id": application_id,
            }
        )
        process_completed_application_data(application_id)

        logger.info(
            {
                "action": "finish_process_completed_application_data_task",
                "message": "finish running process_completed_application_data",
                "application_id": application_id,
            }
        )

    except (Exception, JuloException) as exception_error:
        if self.request.retries > self.max_retries:
            error_data = {
                "action": "failed_process_completed_application_data_task",
                "message": "failed start process_completed_application_data",
                "application_id": application_id,
                "error": str(exception_error),
            }

            logger.exception(error_data)
            error_msg = "Failed start task_completed_application_data {}".format(error_data)
            send_to_slack_notification(error_msg)
            raise exception_error

        logger.info(
            {
                "action": "retry_process_completed_application_data_task",
                "message": "failed start process_completed_application_data",
                "application_id": application_id,
                "error": str(exception_error),
            }
        )
        raise self.retry(exc=exception_error, countdown=60)


@task(bind=True, queue="dana_global_queue", max_retries=3)
def create_dana_customer_field_change_history(
    self, old_data: dict, new_data: dict, customer_id: int
) -> None:
    """
    Create CustomerFieldChange record for updated/changed value in dana customer
    """
    try:
        updated_fields = []

        for field_key in DANA_ONBOARDING_FIELD_TO_TRACK:
            old_attribute = old_data.get(field_key)
            new_attribute = new_data.get(field_key)

            if old_attribute != new_attribute:
                updated_fields.append(
                    CustomerFieldChange(
                        customer_id=customer_id,
                        field_name=field_key,
                        old_value=old_attribute,
                        new_value=new_attribute,
                    )
                )

        CustomerFieldChange.objects.bulk_create(updated_fields)

        logger.info(
            {
                "action": "create_dana_customer_field_change_history",
                "message": (
                    "Success create {} customer_field_change record for customer_id {}".format(
                        len(updated_fields), customer_id
                    )
                ),
            }
        )
    except Exception as exception_error:
        if self.request.retries < self.max_retries:
            logger.info(
                {
                    "action": "create_dana_customer_field_change_history",
                    "message": "Retry to create dana customer_field_change",
                    "old_data": old_data,
                    "new_data": new_data,
                    "customer_id": customer_id,
                    "error": str(exception_error),
                }
            )
            raise self.retry(exc=exception_error, countdown=2)

        logger.exception(
            {
                "action": "create_dana_customer_field_change_history",
                "message": "Failed to create dana customer_field_change",
                "old_data": old_data,
                "new_data": new_data,
                "customer_id": customer_id,
                "error": str(exception_error),
            }
        )
        raise exception_error


@task(queue="dana_global_queue")
def generate_pgood_dana_applications(application_id: int) -> None:
    """
    Hit ANA API to generate pgood for DANA applications
    """
    url = '/api/amp/v1/dana-score/'
    ana_data = {'application_id': application_id}

    try:
        post_anaserver(url, json=ana_data)

        logger.info(
            {
                "action": "generate_pgood_dana_applications",
                "message": "Success generate dana pgood",
                "application_id": application_id,
            }
        )

    except JuloException as err:
        logger.error(
            {
                "action": "generate_pgood_dana_applications",
                "message": "Failed generate dana pgood",
                "application_id": application_id,
                "error": err,
            }
        )


# code deprecated
@task(queue="dana_collection_high_queue")
def trigger_recover_dana_manual_upload():
    fn_name = 'trigger_recover_dana_manual_upload'
    auto_recover_manual_upload_is_blocked = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.DANA_BLOCK_AUTO_RECOVER_MANUAL_UPLOAD, is_active=True
    )
    if auto_recover_manual_upload_is_blocked:
        logger.error(
            {
                "action": fn_name,
                "message": "trigger_recover_dana_manual_upload feature setting is off",
            }
        )
        return

    if is_idempotency_check():
        is_executed = idempotency_check_cron_job(fn_name)
        if is_executed:
            notify_cron_job_has_been_hit_more_than_once(fn_name)
            return

    today = timezone.localtime(timezone.now())
    start_time = today.replace(hour=7, minute=0, second=0)
    end_time = today.replace(hour=22, minute=0, second=0)
    services = AIRudderPDSServices()
    data = services.AI_RUDDER_PDS_CLIENT.query_task_list(
        check_start_time=start_time, check_end_time=end_time
    )
    dana_group_name = DialerSystemConst.GROUP_DANA_B_ALL
    for item in data['list']:
        if item.get('groupName') == dana_group_name:
            task_id = item.get('taskId', None)
            datetime_string = item.get('actualStartTime')
            if not datetime_string:
                continue
            specific_datetime = parser.isoparse(datetime_string)
            dana_process_recover_airudder_for_manual_upload(task_id, specific_datetime, services)


@task(bind=True, queue="dana_global_queue", max_retries=3)
def populate_dana_pusdafil_data_task(self, dana_customer_data_id: int) -> None:
    """
    Create CustomerFieldChange record for updated/changed value in dana customer
    """
    from juloserver.dana.onboarding.services import dana_populate_pusdafil_data

    try:
        dana_customer_data = DanaCustomerData.objects.get(id=dana_customer_data_id)
        dana_populate_pusdafil_data(dana_customer_data)
    except Exception as exception_error:
        if self.request.retries < self.max_retries:
            logger.info(
                {
                    "action": "populate_dana_pusdafil_data_task",
                    "message": "Retry to populate_dana_pusdafil_data_task",
                    "dana_customer_data_id": dana_customer_data_id,
                    "error": str(exception_error),
                }
            )
            raise self.retry(exc=exception_error, countdown=2)

        logger.exception(
            {
                "action": "populate_dana_pusdafil_data_task",
                "message": "Failed to populate_dana_pusdafil_data_task",
                "error": str(exception_error),
            }
        )
        raise exception_error


@task(queue='partnership_global')
def trigger_dana_fdc_inquiry(
    fdc_inquiry_id=None,
    application_ktp=None,
    custom_queue: str = 'partnership_global',
):
    fdc_inquiry_data = {'id': fdc_inquiry_id, 'nik': application_ktp}
    run_dana_fdc_request.apply_async(
        args=(fdc_inquiry_data, 1),
        kwargs={
            'retry_count': 0,
            'retry': False,
            'source': 'triggered from trigger_dana_fdc_inquiry',
            'custom_queue': custom_queue,
        },
        queue=custom_queue,
    )


@task(queue='partnership_global')
def run_dana_fdc_request(
    fdc_inquiry_data,
    reason,
    retry_count=0,
    retry=False,
    custom_queue: str = 'partnership_global',
    source=None,
):
    try:
        try:
            logger.info(
                {
                    "function": "run_dana_fdc_request",
                    "action": "call get_and_save_fdc_data",
                    "fdc_inquiry_data": fdc_inquiry_data,
                    "reason": reason,
                    "retry_count": retry_count,
                    "retry": retry,
                    "source": source,
                }
            )
            get_and_save_fdc_data(fdc_inquiry_data, reason, retry)
        except ObjectDoesNotExist as err:
            log_message = {
                "function": "run_dana_fdc_request",
                "action": "call get_and_save_fdc_data",
                "source": source,
                "reason": str(err),
                "fdc_inquiry_id": fdc_inquiry_data.get("id"),
                "nik": fdc_inquiry_data.get("nik"),
                "application_status": None,
            }
            nik = log_message.get("nik")
            if nik:
                application = Application.objects.filter(ktp=nik).last()
                if application:
                    log_message["application_status"] = application.application_status.status_code

            logger.error(log_message)
            return

        fdc_inquiry = FDCInquiry.objects.get(id=fdc_inquiry_data['id'])
        if not fdc_inquiry:
            return

        application_id = fdc_inquiry.application_id
        application = Application.objects.get_or_none(id=application_id)
        app_status = application.application_status.status_code

        dana_fdc_result = DanaFDCResult.objects.filter(application_id=application.id).last()
        if dana_fdc_result and dana_fdc_result.fdc_status == DanaFDCResultStatus.INIT:
            process_dana_fdc_result.delay(application.id)

        if app_status != ApplicationStatusCodes.LOC_APPROVED or reason != 2:
            return

        if not application.is_julo_one():
            return

    except FDCServerUnavailableException:
        logger.error(
            {
                "action": "run_dana_fdc_request",
                "error": "FDC server can not reach",
                "data": fdc_inquiry_data,
            }
        )

    except Exception as e:
        sentry_client = get_julo_sentry_client()
        sentry_client.captureException()
        logger.info(
            {
                "action": "run_dana_fdc_request",
                "message": "retry fdc request with error: %(e)s" % {'e': e},
            }
        )
    else:
        return

    # variable reason equal to 1 is for FDCx100
    if reason != 1:
        return

    fdc_retry_feature = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.RETRY_FDC_INQUIRY, category="fdc", is_active=True
    ).first()

    if not fdc_retry_feature:
        logger.info({"action": "run_dana_fdc_request", "error": "fdc_retry_feature is not active"})
        return

    params = fdc_retry_feature.parameters
    retry_interval_minutes = params['retry_interval_minutes']
    max_retries = params['max_retries']

    if retry_interval_minutes == 0:
        raise JuloException(
            "Parameter retry_interval_minutes: %(retry_interval_minutes)s can not be zero value"
            % {'retry_interval_minutes': retry_interval_minutes}
        )
    if not isinstance(retry_interval_minutes, int):
        raise JuloException("Parameter retry_interval_minutes should integer")

    if not isinstance(max_retries, int):
        raise JuloException("Parameter max_retries should integer")
    if max_retries <= 0:
        raise JuloException("Parameter max_retries should greater than zero")

    countdown_seconds = retry_interval_minutes * 60

    if retry_count > max_retries:
        logger.info(
            {
                "action": "run_dana_fdc_request",
                "message": "Retry FDC Inquiry has exceeded the maximum limit",
            }
        )

        return

    retry_count += 1

    logger.info(
        {
            'action': 'run_dana_fdc_request',
            'fdc_inquiry_data': fdc_inquiry_data,
            'message': 'failure_status',
            'retry_count': retry_count,
            'count_down': countdown_seconds,
        }
    )

    run_dana_fdc_request.apply_async(
        args=(fdc_inquiry_data, reason),
        kwargs={
            'retry_count': retry_count,
            'retry': retry,
            'source': source,
            'custom_queue': custom_queue,
        },
        countdown=countdown_seconds,
        queue=custom_queue,
    )


@task(
    bind=True,
    name='process_sending_dana_fdc_result',
    queue='dana_callback_fdc_status_queue',
    max_retries=3,
)
def process_sending_dana_fdc_result(self, application_id: int) -> None:
    feature_setting = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.DANA_FDC_RESULT_RETRY_CONFIGURATION,
        is_active=True,
    ).last()

    if not feature_setting or not feature_setting.parameters.get('retry_policy'):
        logger.error(
            {
                "action": "failed_dana_send_fdc_status",
                "message": "feature is off",
            }
        )
        return

    curr_retries_attempt = process_sending_dana_fdc_result.request.retries
    max_retries = process_sending_dana_fdc_result.max_retries

    logger.info(
        {
            "action": "process_sending_dana_fdc_result_retry",
            "application_id": application_id,
            "retry_attempts": curr_retries_attempt,
            "max_retries": max_retries,
        }
    )

    retry_delay = feature_setting.parameters.get('retry_policy').get('interval_retry_times')
    timeout = feature_setting.parameters.get('retry_policy').get('timeout')
    failed_internal_server_error = False
    dana_customer_identifier = None
    headers = None
    api_url = None
    payload = None
    response_results = None
    dana_fdc_result = None

    with transaction.atomic('bureau_db'):
        try:
            dana_fdc_result = (
                DanaFDCResult.objects.select_for_update()
                .filter(application_id=application_id)
                .last()
            )

            if not dana_fdc_result:
                logger.error(
                    {
                        "application_id": application_id,
                        "action": "failed_getting_fdc_result",
                        "message": "application not have data dana_fdc_result",
                    }
                )
                return

            dana_customer_data = DanaCustomerData.objects.filter(
                dana_customer_identifier=dana_fdc_result.dana_customer_identifier,
                lender_product_id=dana_fdc_result.lender_product_id,
            ).last()

            if not dana_customer_data:
                logger.error(
                    {
                        "application_id": application_id,
                        "action": "failed_getting_fdc_result",
                        "message": "dana_customer_data not found",
                    }
                )
                return

            dana_customer_identifier = dana_customer_data.dana_customer_identifier

            if dana_fdc_result.status in (
                DanaFDCStatusSentRequest.SUCCESS,
                DanaFDCStatusSentRequest.PROCESS,
            ):
                logger.error(
                    {
                        "action": "dana_send_fdc_status_already_send_or_in_process",
                        "message": "please wait and re check the dana_fdc_result.status",
                        "dana_customer_identifier": dana_customer_identifier,
                        "application_id": application_id,
                        "status": dana_fdc_result.status,
                    }
                )
                return

            if dana_fdc_result.fdc_status == DanaFDCResultStatus.INIT:
                logger.error(
                    {
                        "action": "dana_send_fdc_status_is_init_status",
                        "message": "Dana FDC Result status still init",
                        "dana_customer_identifier": dana_customer_identifier,
                        "application_id": application_id,
                        "status": dana_fdc_result.status,
                    }
                )
                return

            # Update to process status, if locking happen this for idempotency check on early check
            dana_fdc_result.update_safely(status=DanaFDCStatusSentRequest.PROCESS)

            api_url = settings.DANA_API_BASE_URL + DanaEndpointAPI.UPDATE_ACCOUNT_INFO
            tz = pytz.timezone("Asia/Jakarta")
            now = datetime.now(tz=tz)
            x_timestamp = "{}+07:00".format(now.strftime("%Y-%m-%dT%H:%M:%S"))

            payload = {
                "customerId": dana_customer_identifier,
                "lenderProductId": dana_customer_data.lender_product_id,
                "updateInfoList": [
                    {
                        "updateKey": "FDCFlag",
                        "updateValue": dana_fdc_result.fdc_status,
                        "updateAdditionalInfo": DanaFDCResultStatus.ADDITIONAL_INFO[
                            dana_fdc_result.fdc_status
                        ],
                    }
                ],
            }

            x_signature = create_x_signature(
                payload=payload,
                timestamp=x_timestamp,
                method='POST',
                endpoint=DanaEndpointAPI.UPDATE_ACCOUNT_INFO,
            )

            x_external_id = str(uuid.uuid4()).replace("-", "")
            headers = {
                'Content-Type': 'application/json',
                'X-TIMESTAMP': x_timestamp,
                'X-SIGNATURE': x_signature,
                'X-PARTNER-ID': DANA_HEADER_X_PARTNER_ID,
                'X-EXTERNAL-ID': x_external_id,
                'CHANNEL-ID': DANA_HEADER_CHANNEL_ID,
            }

            response = requests.post(api_url, headers=headers, json=payload, timeout=timeout)
            response_results = response.json()

            if not response_results:
                response_results = None

            if response.status_code == status.HTTP_200_OK:
                logger.info(
                    {
                        "action": "dana_success_send_fdc_status",
                        "message": "success send status fdc",
                        "customer_id": dana_customer_identifier,
                        "application_id": application_id,
                        "header": headers,
                        "payload": payload,
                        "api_url": api_url,
                        "response": response_results,
                    }
                )
                dana_fdc_result.update_safely(status=DanaFDCStatusSentRequest.SUCCESS)
                return
            elif response.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR:
                logger.error(
                    {
                        "action": "failed_dana_send_fdc_status_internal_server_error",
                        "message": "failed send status fdc internal server error",
                        "customer_id": dana_customer_identifier,
                        "application_id": application_id,
                        "header": headers,
                        "payload": payload,
                        "api_url": api_url,
                        "response": response_results,
                    }
                )

                response_body = response.json()
                dana_response_code = response_body.get('responseCode')
                if dana_response_code and dana_response_code == str(
                    AccountUpdateResponseCode.INTERNAL_SERVER_ERROR.code
                ):
                    failed_internal_server_error = True
                    raise TimeoutError(
                        'sending_fdc_result app_id={} dana_customer_id={} server_error'.format(
                            application_id, dana_customer_identifier
                        )
                    )
            else:
                raise JuloException(
                    'sending_fdc_result app_id={} dana_customer_id={} failed'.format(
                        application_id, dana_customer_identifier
                    )
                )

        except JuloException as exception_error:
            if dana_fdc_result:
                dana_fdc_result.update_safely(status=DanaFDCStatusSentRequest.FAIL)

            logger.error(
                {
                    "action": "failed_dana_send_fdc_status_not_find_response",
                    "message": "failed send status fdc not find response",
                    "customer_id": dana_customer_identifier,
                    "application_id": application_id,
                    "api_url": api_url,
                    "error": str(exception_error),
                }
            )
            return
        except Exception as exception_error:
            if self.request.retries > self.max_retries:
                if dana_fdc_result:
                    if failed_internal_server_error:
                        dana_fdc_result.update_safely(status=DanaFDCStatusSentRequest.SUSPENDED)
                    else:
                        dana_fdc_result.update_safely(status=DanaFDCStatusSentRequest.PENDING)

                logger.error(
                    {
                        "action": "failed_dana_send_fdc_status",
                        "message": "failed send status fdc",
                        "fail_internal_server_error": failed_internal_server_error,
                        "customer_id": dana_customer_identifier,
                        "application_id": application_id,
                        "api_url": api_url,
                        "error": str(exception_error),
                    }
                )

                return

            if dana_fdc_result:
                dana_fdc_result.update_safely(status=DanaFDCStatusSentRequest.PENDING)

            logger.info(
                {
                    "action": "retry_sending_dana_fdc_result",
                    "message": "retry to send status fdc",
                    "customer_id": dana_customer_identifier,
                    "application_id": application_id,
                    "header": headers,
                    "payload": payload,
                    "api_url": api_url,
                    "response": response_results,
                    "error": str(exception_error),
                }
            )

            raise self.retry(exc=exception_error, countdown=retry_delay)


@task(queue="dana_global_queue")
def trigger_resume_dana_application_stuck():
    from juloserver.dana.onboarding.services import (
        validate_dana_binary_check,
        process_application_to_105,
        process_valid_application,
        dana_reject_manual_stuck,
    )
    from juloserver.dana.handlers import Dana130Handler, Dana105Handler

    application_stuck_statuses = {
        ApplicationStatusCodes.FORM_CREATED,
        ApplicationStatusCodes.FORM_PARTIAL,
        ApplicationStatusCodes.APPLICANT_CALLS_SUCCESSFUL,
    }
    workflow = Workflow.objects.get(name=WorkflowConst.DANA)

    current_time = timezone.localtime(timezone.now())
    check_time = current_time - timedelta(hours=1)
    end_time = check_time - timedelta(hours=1)
    applications = Application.objects.select_related("dana_customer_data").filter(
        application_status_id__in=application_stuck_statuses,
        workflow=workflow,
        cdate__lt=check_time,
        cdate__gte=end_time,
    )
    if len(applications) == 0:
        return

    application_ids = list(applications.values_list('id', flat=True))
    logger.info(
        {
            'action': 'trigger_resume_dana_application_stuck',
            'application_ids': application_ids,
        }
    )
    dana_application_references = DanaApplicationReference.objects.filter(
        application_id__in=application_ids
    )
    mapping_dana_application_reference = {}
    for dar in dana_application_references.iterator():
        mapping_dana_application_reference[dar.application_id] = dar

    mapping_dana_fdc_result = {}
    dana_fdc_results = DanaFDCResult.objects.filter(application_id__in=application_ids)
    for dfr in dana_fdc_results.iterator():
        mapping_dana_fdc_result[dfr.application_id] = True

    feature_setting = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.DANA_WHITELIST_USERS,
    ).first()

    for application in applications.iterator():
        rejected = dana_reject_manual_stuck(application)
        resume_105 = False
        if rejected:
            continue
        if application.application_status_id == ApplicationStatusCodes.FORM_CREATED:
            process_application_to_105(application.id)
            resume_105 = True
        if application.application_status_id == ApplicationStatusCodes.FORM_PARTIAL or resume_105:
            dana_fdc_result = mapping_dana_fdc_result.get(application.id)
            # rerun handler if doesnt have dana fdc result
            if not dana_fdc_result:
                handler105 = Dana105Handler(application, None, None, None, None)
                handler105.async_task()

            dana_customer_data = application.dana_customer_data
            dana_application_reference = mapping_dana_application_reference.get(application.id)
            user_whitelisted = (
                feature_setting
                and feature_setting.is_active
                and str(dana_customer_data.dana_customer_identifier)
                in feature_setting.parameters['dana_customer_identifiers']
            )
            error_status_code, _ = validate_dana_binary_check(
                dana_customer_data,
                user_whitelisted,
                dana_application_reference,
                application.id,
                dana_customer_data.mobile_number,
                dana_customer_data.nik,
            )
            if error_status_code:
                continue
            process_valid_application(application.id)

        if application.application_status_id == ApplicationStatusCodes.APPLICANT_CALLS_SUCCESSFUL:
            handler = Dana130Handler(application, None, None, None, None)
            handler.post()
