import base64
import csv
import logging
import os
import re
import tempfile
from datetime import timedelta, datetime
from io import BytesIO

import pdfkit
import requests
from babel.dates import format_date
from bulk_update.helper import bulk_update
from celery.task import task
from django.conf import settings
from django.core.files import File
from django.db import transaction
from django.db.models import CharField, F, Func, Value
from django.template import (
    Context,
    Template,
)
from django.template.loader import render_to_string, get_template
from django.utils import timezone
from PIL import Image as Imagealias
from rest_framework import status
from babel.dates import format_datetime

import juloserver.pin.services as pin_services
from juloserver.account.models import AccountLimit
from juloserver.account_payment.models import AccountPayment
from juloserver.apiv2.services import check_iti_repeat
from juloserver.application_flow.constants import PartnerNameConstant
from juloserver.application_flow.services import JuloOneService
from juloserver.fdc.exceptions import FDCServerUnavailableException
from juloserver.fdc.services import get_and_save_fdc_data
from juloserver.digisign.constants import SigningStatus
from juloserver.digisign.models import DigisignDocument
from juloserver.income_check.services import check_salary_izi_data, is_income_in_range
from juloserver.julo.clients import get_julo_email_client, get_julo_sentry_client
from juloserver.julo.constants import (
    FeatureNameConst,
    ProductLineCodes,
    UploadAsyncStateStatus,
    UploadAsyncStateType,
    WorkflowConst,
)
from juloserver.julo.exceptions import JuloException, EmailNotSent
from juloserver.julo.models import (
    Application,
    Customer,
    EmailHistory,
    FeatureSetting,
    Image,
    JobType,
    Loan,
    Partner,
    PaymentMethod,
    UploadAsyncState,
    OtpRequest,
    Workflow,
    ApplicationFieldChange,
)
from juloserver.julo.services2.high_score import feature_high_score_full_bypass
from juloserver.julo.services import process_application_status_change
from juloserver.julo.statuses import (
    ApplicationStatusCodes,
    LoanStatusCodes,
)
from juloserver.julo.utils import display_rupiah, upload_file_to_oss, upload_file_as_bytes_to_oss
from juloserver.julo_privyid.services.common import get_privy_feature
from juloserver.julocore.python2.utils import py2round
from juloserver.partnership.clients import get_partnership_email_client
from juloserver.partnership.constants import (
    PARTNERSHIP_CALLBACK_URL_STRING,
    Partnership_callback_mapping_statuses,
    PartnershipImageProductType,
    PartnershipImageStatus,
    PartnershipPreCheckFlag,
    PartnershipProductFlow,
    PartnershipTokenType,
    PartnershipTypeConstant,
    PartnershipUploadImageDestination,
    ProductFinancingUploadActionType,
    LoanDurationType,
    PartnershipImageType,
    PartnershipFeatureNameConst,
    PartnershipFlag,
)
from juloserver.partnership.crm.repayment_service import product_financing_loan_repayment_upload
from juloserver.partnership.jwt_manager import JWTManager
from juloserver.partnership.models import (
    PartnershipApplicationFlag,
    PartnershipConfig,
    PartnershipCustomerCallbackToken,
    PartnershipFlowFlag,
    PartnershipImage,
    PartnerLoanRequest,
    PartnershipFeatureSetting,
    AnaPartnershipNullPartner,
    PartnershipTransaction,
)
from juloserver.julo.partners import PartnerConstant
from juloserver.loan.services.loan_related import update_loan_status_and_loan_history
from juloserver.partnership.services.digisign import partnership_sign_with_digisign
from juloserver.portal.object.bulk_upload.constants import (
    MerchantFinancingSKRTPNewTemplate,
)
from juloserver.portal.object.bulk_upload.skrtp_service.service import get_mf_skrtp_content
from juloserver.julo.banks import BankManager
from juloserver.partnership.utils import (
    partnership_detokenize_sync_object_model,
    get_fs_send_email_disbursement_notification,
)

from juloserver.pii_vault.constants import (
    PiiSource,
    PiiVaultDataType,
)

logger = logging.getLogger(__name__)
PARTNER_ATTEMPT_LIMIT = 3


@task(name='trigger_partnership_callback', queue='partner_leadgen_global_queue')
def trigger_partnership_callback(application_id, new_status_code, is_notification=False, attempt=0):
    application = Application.objects.filter(id=application_id).last()
    if not application:
        return

    callback_status = None

    if is_notification and new_status_code == ApplicationStatusCodes.FORM_CREATED:
        callback_status = ApplicationStatusCodes.FORM_CREATED
    else:
        for partner_status in Partnership_callback_mapping_statuses:
            if new_status_code in partner_status.list_code:
                callback_status = partner_status.mapping_status

    if not callback_status:
        return

    partner = application.partner
    if not partner:
        return

    if new_status_code == ApplicationStatusCodes.ACTIVATION_CALL_SUCCESS_AND_BANK_VALIDATE_ONGOING:
        if not get_privy_feature():
            return

    headers = dict()
    url = ''
    partnership_callback = PartnershipCustomerCallbackToken.objects.filter(
        partner=partner, customer=application.customer
    ).last()
    if not partnership_callback:
        partner_config = PartnershipConfig.objects.get_or_none(partner=partner)
        if not partner_config or not partner_config.callback_url:
            return

        if partner_config.callback_token:
            headers = {'Authorization': '%s' % partner_config.callback_token}
        url = partner_config.callback_url + PARTNERSHIP_CALLBACK_URL_STRING
    else:
        url = partnership_callback.callback_url
        headers = {'Authorization': partnership_callback.callback_token}

    application.refresh_from_db()
    request_data = {
        'application_xid': application.application_xid,
        'application_status': application.partnership_status,
        'notification_customer_to_continue_register': is_notification
    }
    response = requests.post(
        url=url,
        headers=headers,
        json=request_data
    )
    logger.info(
        {
            "action": "trigger_partnership_callback",
            "url": url,
            "data": request_data,
            "attempt": attempt,
            "response": response,
            "status_code": response.status_code,
            "new_status_code": new_status_code,
            "application_status_code": application.application_status_id,
            "notification_customer_to_continue_register": is_notification
        }
    )

    if response and response.status_code not in [
        status.HTTP_200_OK,
        status.HTTP_201_CREATED
    ] and attempt <= PARTNER_ATTEMPT_LIMIT:
        trigger_partnership_callback.delay(
            application_id, new_status_code,
            is_notification, attempt + 1
        )


@task(name='send_email_efishery_account_payments_report', queue='partner_mf_cronjob_queue')
def send_email_efishery_account_payments_report():
    efishery_report_feature = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.SEND_EMAIL_EFISHERY_ACCOUNT_PAYMENTS_REPORT,
        is_active=True
    ).last()
    if not efishery_report_feature:
        return

    dpd = -3
    dpd_parameter = efishery_report_feature.parameters.get('dpd')
    if dpd_parameter and isinstance(dpd_parameter, int):
        dpd = dpd_parameter
    today_date = timezone.localtime(timezone.now()).date()
    due_date = today_date - timedelta(days=dpd)
    account_payments = AccountPayment.objects.filter(
        account__customer__application__product_line=ProductLineCodes.EFISHERY,
        payment__loan__loan_status__lt=LoanStatusCodes.PAID_OFF,
        due_date=due_date
    ).annotate(
        disbursement_date_formatted=Func(
            F('payment__loan__fund_transfer_ts'),
            Value('dd-MM-yyyy'),
            function='to_char',
            output_field=CharField()
        ),
        due_date_formatted=Func(
            F('due_date'),
            Value('dd-MM-yyyy'),
            function='to_char',
            output_field=CharField()
        ),
    ).values_list(
        'account__customer__application__application_xid',
        'payment__loan__loan_xid', 'account__customer__fullname',
        'payment__loan__loan_amount', 'due_amount', 'paid_amount',
        'disbursement_date_formatted', 'due_date_formatted'
    )
    if not account_payments:
        return

    header = ('application_xid', 'loan_xid', 'fullname', 'loan_amount',
              'due_amount', 'paid_amount', 'disbursement_date', 'due_date')

    temp_dir = tempfile.gettempdir()
    file_name = 'efisher_report_{}.csv'.format(today_date.strftime("%m%d%Y"))
    file_path = os.path.join(temp_dir, file_name)
    with open(file_path, 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(header)
        writer.writerows(account_payments)
    with open(file_path, 'rb') as f:
        data = f.read()
    encoded = base64.b64encode(data)
    if os.path.exists(file_path):
        os.remove(file_path)

    attachment_dict = {
        "content": encoded.decode(),
        "filename": file_name,
        "type": "text/csv"
    }
    email_from = "ops.efishery@julo.co.id"
    email_to = ["lutfie.rismawan@efishery.com",
                "ganda.nugraha@efishery.com",
                "rizki.ardiansyah@efishery.com"]
    email_cc = ["israbalthazar@julo.co.id",
                "farandi@julo.co.id",
                "james.salim@julo.co.id",
                "finance@julofinance.com",
                "salsabila.yulianti@julo.co.id",
                "ray.anjasta@julo.co.id"]
    email_to_parameter = efishery_report_feature.parameters.get('email_to')
    email_cc_parameter = efishery_report_feature.parameters.get('email_cc')
    if email_to_parameter and isinstance(email_to_parameter, list):
        email_to = email_to_parameter

    if email_cc_parameter and isinstance(email_cc_parameter, list):
        email_cc = email_cc_parameter

    content = "efishery report {}".format(today_date.strftime("%m-%d-%Y"))
    subject = "efishery report"
    julo_email_client = get_julo_email_client()
    julo_email_client.send_email(
        subject=subject, content=content, email_to=email_to, email_from=email_from,
        email_cc=email_cc, attachment_dict=attachment_dict, content_type="text/html"
    )


@task(name='email_notification_for_partner_loan', queue='partner_mf_global_queue')
def email_notification_for_partner_loan(loan_id, product_line_code, send_to=None):
    loan = Loan.objects.get(id=loan_id)
    application = loan.account.last_application
    recipients_email_address_for_bulk_disbursement = application.partner. \
        recipients_email_address_for_bulk_disbursement

    if not application.partner.is_email_send_to_customer:
        if not send_to:
            if recipients_email_address_for_bulk_disbursement:
                send_to = recipients_email_address_for_bulk_disbursement
    else:
        if not send_to:
            send_to = application.email

    # send email vars
    partner_email_from = application.partner.sender_email_address_for_bulk_disbursement
    message = "email address for bulk disbursement not found"
    if (
        not recipients_email_address_for_bulk_disbursement and not send_to
    ) or not partner_email_from:
        if not partner_email_from:
            message = "{} sender {}".format(application.partner.name, message)
        else:
            message = "{} recipients {}".format(application.partner.name, message)
        raise Exception(message)
    # email history
    partner_template_code = "{}_220_email".format(application.partner.name)

    account = application.account
    loans = account.get_all_active_loan().prefetch_related("payment_set")
    for loan in loans.iterator():
        is_email_exists = EmailHistory.objects.filter(
            customer_id=application.customer_id,
            application_id=application.id,
            payment_id=loan.payment_set.first().id,
            template_code=partner_template_code,
        ).exists()
        if is_email_exists:
            logger.error(
                {
                    "action": "email_notification_for_partner_loan",
                    "message": "email already sent for Loan: {}".format(loan.id),
                    "application_xid": application.application_xid,
                }
            )
            continue

        context = {
            'fullname': application.fullname_with_title,
            'loan_amount': display_rupiah(loan.loan_amount),
            'loan_disbursed_amount': display_rupiah(loan.loan_disbursement_amount),
            'due_date': format_date(
                loan.payment_set.order_by('id').first().due_date, 'dd-MM-yyyy', locale='id_ID'
            ),
        }

        context = Context(context)
        email_template = render_to_string(
            'email_pilot_partner_success_disburse.html',
            context=context
        )
        template = Template(email_template)
        email_from = partner_email_from
        email_to = send_to
        email_cc = application.partner.cc_email_address_for_bulk_disbursement
        subject = "Pinjaman JULO telah aktif dan dana telah dicairkan"
        attachment_dict, content_type = __get_sphp_attachment(loan)
        julo_email_client = get_julo_email_client()
        msg = str(template.render(context))
        status, _, headers = julo_email_client.send_email(
            subject, msg, email_to, email_from=email_from, email_cc=email_cc,
            attachment_dict=attachment_dict, content_type=content_type
        )
        EmailHistory.objects.create(
            customer_id=application.customer_id,
            application_id=application.id,
            payment_id=loan.payment_set.first().id,
            to_email=email_to,
            subject=subject,
            message_content=msg,
            template_code=partner_template_code,
            sg_message_id=headers['X-Message-Id'],
        )


@task(queue='partner_mf_global_queue')
def partnership_mfsp_send_email_disbursement_notification(
    loan, application, template_code, send_to
):
    is_already_sent = EmailHistory.objects.filter(
        customer_id=application.customer_id,
        application_id=application.id,
        payment_id=loan.payment_set.first().id,
        template_code=template_code,
    ).exists()
    if is_already_sent:
        return

    partner = application.partner
    detokenize_partner = partnership_detokenize_sync_object_model(
        PiiSource.PARTNER,
        partner,
        fields_param=['sender_email_address_for_bulk_disbursement'],
        pii_type=PiiVaultDataType.KEY_VALUE,
    )
    partner_email_from = detokenize_partner.sender_email_address_for_bulk_disbursement
    if not partner_email_from:
        logger.error(
            {
                'action': 'partnership_mfsp_send_email_disbursement_notification',
                'loan_id': loan.id,
                'message': "Error - None sender_email_address_for_bulk_disbursement",
            }
        )
        return

    context = {
        'fullname': application.fullname_with_title,
        'loan_amount': display_rupiah(loan.loan_amount),
        'loan_disbursed_amount': display_rupiah(loan.loan_disbursement_amount),
        'due_date': format_date(
            loan.payment_set.order_by('id').first().due_date, 'dd-MM-yyyy', locale='id_ID'
        ),
    }

    context = Context(context)
    email_template = render_to_string('email_pilot_partner_success_disburse.html', context=context)
    template = Template(email_template)
    email_from = partner_email_from
    email_to = send_to
    email_cc = application.partner.cc_email_address_for_bulk_disbursement
    subject = "Pinjaman JULO telah aktif dan dana telah dicairkan"
    attachment_dict, content_type = __get_sphp_attachment(loan)
    julo_email_client = get_julo_email_client()
    msg = str(template.render(context))
    status, _, headers = julo_email_client.send_email(
        subject,
        msg,
        email_to,
        email_from=email_from,
        email_cc=email_cc,
        attachment_dict=attachment_dict,
        content_type=content_type,
    )
    EmailHistory.objects.create(
        customer_id=application.customer_id,
        application_id=application.id,
        payment_id=loan.payment_set.first().id,
        to_email=email_to,
        subject=subject,
        message_content=msg,
        template_code=template_code,
        sg_message_id=headers['X-Message-Id'],
    )


@task(queue='partner_mf_global_queue')
def partnership_mfsp_send_email_disbursement_notification_task(loan_id):
    fn_name = 'partnership_send_email_disbursement_notification'
    loan = Loan.objects.filter(pk=loan_id).first()
    application = loan.get_application
    partner_name = application.partner.name_detokenized
    try:
        (
            err,
            partner_email,
            send_to_partner,
            send_to_borrower,
        ) = get_fs_send_email_disbursement_notification(partner_name)
        if err:
            logger.error(
                {
                    'action': fn_name,
                    'loan_id': loan.id,
                    'message': "Error get_fs_send_email_disbursement_notification",
                    'errors': err,
                }
            )
            return

        logger.info(
            {
                'action': fn_name,
                'loan_id': loan.id,
                'partner_name': partner_name,
                'partner_email': partner_email,
                'send_to_partner': send_to_partner,
                'send_to_borrower': send_to_borrower,
            }
        )

        if send_to_partner:
            partnership_mfsp_send_email_disbursement_notification(
                loan, application, 'mfsp_disbursement_email_partner', partner_email
            )

        if send_to_borrower:
            detokenize_partnership_customer_data = partnership_detokenize_sync_object_model(
                PiiSource.PARTNERSHIP_CUSTOMER_DATA,
                loan.account.partnership_customer_data,
                loan.customer.customer_xid,
                ['email'],
            )
            send_to = detokenize_partnership_customer_data.email
            partnership_mfsp_send_email_disbursement_notification(
                loan, application, 'mfsp_disbursement_email_borrower', send_to
            )

    except Exception as e:
        logger.error(
            {
                'action': fn_name,
                'loan_id': loan.id,
                'message': "Error Exception",
                'errors': str(e),
            }
        )
        return


def __get_partner_sphp_content(loan):
    application = loan.account.last_application
    value = loan.product.late_fee_pct * loan.installment_amount
    late_fee_amount = py2round(value if value > 55000 else 55000, -2)
    sphp_context = {
        'julo_image': settings.SPHP_STATIC_FILE_PATH + 'scraoe-copy-3@3x.png',
        'loan_xid': loan.loan_xid,
        'loan_date': format_date(loan.cdate, 'dd-MM-yyyy', locale='id_ID'),
        'application_xid': application.application_xid,
        'application_x190_date': format_date(
            application.cdate, 'dd-MM-yyyy', locale='id_ID'
        ),
        'fullname': application.fullname,
        'loan_amount': display_rupiah(loan.loan_amount),
        'available_limit': display_rupiah(loan.account.accountlimit_set.last().available_limit),
        'provision_fee_amount': display_rupiah(loan.provision_fee()),
        'interest_rate_in_pct': '{}%'.format(loan.interest_percent_monthly()),
        'late_fee_amount': display_rupiah(late_fee_amount),
        'total_late_fee_amount': display_rupiah(loan.loan_amount),
        'julo_bank_name': loan.julo_bank_name,
        'julo_bank_code': '-',
        'julo_bank_account_number': loan.julo_bank_account_number,
    }

    if 'bca' not in loan.julo_bank_name.lower():
        payment_method = PaymentMethod.objects.filter(
            virtual_account=loan.julo_bank_account_number
        ).first()
        if payment_method:
            sphp_context['julo_bank_code'] = payment_method.bank_code
    payments = loan.payment_set.all().order_by('id')
    for payment in payments:
        payment.due_date = format_date(payment.due_date, 'd MMM yy', locale='id_ID')
        payment.due_amount = display_rupiah(payment.due_amount + payment.paid_amount)
    sphp_context['payments'] = payments

    sphp_context = Context(sphp_context)
    sphp_partner_template = 'sphp_pilot_merchant_financing_disbursement_upload_template.html'
    if application.product_line_code == ProductLineCodes.BUKUWARUNG:
        sphp_partner_template = 'sphp_pilot_bukuwarung_disbursement_upload_template.html'

    sphp_template = render_to_string(sphp_partner_template, context=sphp_context)

    return sphp_template


def __get_sphp_attachment(loan):
    account_limit = None

    application = loan.account.last_application
    attachment_name = "%s-%s.pdf" % (application.fullname, application.application_xid)
    MerchantFinancingSKRTPNewTemplate.append(PartnerConstant.AXIATA_PARTNER)
    if application.partner and application.partner.name in MerchantFinancingSKRTPNewTemplate:
        if application.partner.name != PartnerConstant.AXIATA_PARTNER:
            account = application.account
            if not account:
                raise Exception(
                    "account data not found for this application_id {}".format(application.id)
                )

            account_limit = AccountLimit.objects.filter(account=account).last()
            if not account_limit:
                raise Exception("account_limit data not found for this loan_id {}".format(loan.id))

        attachment_string = get_mf_skrtp_content(application, loan, account_limit)
    else:
        attachment_string = __get_partner_sphp_content(loan)
    temp_dir = tempfile.mkdtemp()
    file_path = os.path.join(temp_dir, attachment_name)
    pdfkit.from_string(attachment_string, file_path)
    with open(file_path, 'rb') as f:
        sphp_data = f.read()
        f.close()
    pdf_content = base64.b64encode(sphp_data).decode()
    if os.path.exists(file_path):
        os.remove(file_path)

    sphp_dict = {
        "content": pdf_content,
        "filename": attachment_name,
        "type": "application/pdf"
    }
    return sphp_dict, "text/html"


@task(name='notify_user_to_check_submission_status_via_email', queue='partner_leadgen_global_queue')
def notify_user_to_check_submission_status(application_id: int) -> None:
    application = Application.objects.get(id=application_id)

    # Don't send this email if application exists in PartnershipApplicationFlag
    partnership_application_flag = PartnershipApplicationFlag.objects.filter(
        application_id=application_id,
        name=PartnershipPreCheckFlag.APPROVED,
    ).exists()
    if partnership_application_flag:
        return

    email_sended = get_partnership_email_client().email_notify_user_to_check_submission_status(
        application
    )

    EmailHistory.objects.create(
        customer=email_sended.customer,
        sg_message_id=email_sended.headers["X-Message-Id"],
        to_email=email_sended.email_to,
        subject=email_sended.subject,
        message_content=email_sended.message,
        status=str(email_sended.status),
    )


@task(name='notify_user_linking_account_via_email', queue='paylater_global_queue')
def notify_user_linking_account(customer_id: int, partner_id: int) -> None:
    customer = Customer.objects.get(id=customer_id)
    partner = Partner.objects.get(id=partner_id)
    email_sended = get_partnership_email_client().email_success_linking_account(
        customer, partner
    )

    EmailHistory.objects.create(
        customer=email_sended.customer,
        sg_message_id=email_sended.headers["X-Message-Id"],
        to_email=email_sended.email_to,
        subject=email_sended.subject,
        message_content=email_sended.message,
        status=str(email_sended.status),
    )


@task(name="upload_image_to_partnership_image", queue="partner_mf_cronjob_queue")
def upload_partnership_image(partnership_image_id: int) -> None:
    partnership_image = PartnershipImage.objects.get_or_none(pk=partnership_image_id)
    if not partnership_image:
        logger.error({"partnership_image": partnership_image_id, "status": "not_found"})
        JuloException(
            {"partnership_image": partnership_image_id, "status": "not_found"}
        )

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
    image_path = partnership_image.image.path
    _, file_extension = os.path.splitext(partnership_image.image.name)
    filename = "%s_%s%s" % (
        partnership_image.image_type,
        str(partnership_image.id),
        file_extension,
    )
    image_remote_filepath = "/".join(
        ["cust_" + cust_id, "partnership_image_application", filename]
    )

    upload_file_to_oss(
        settings.OSS_MEDIA_BUCKET, partnership_image.image.path, image_remote_filepath
    )
    partnership_image.url = image_remote_filepath
    partnership_image.save()

    logger.info(
        {
            "status": "successfull upload image to s3",
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

    # Delete a local file
    if os.path.isfile(image_path):
        logger.info(
            {
                "action": "deleting_local_file",
                "image_path": image_path,
                "partnership_application_id": partnership_image.application_image_source,
                "image_type": partnership_image.image_type,
            }
        )
        partnership_image.image.delete()


@task(name='send_notification_reminders_to_klop_customer', queue='partner_leadgen_global_queue')
def send_notification_reminders_to_klop_customer():
    """
    This async task for sending notification to customer that registered in
    klop but not filled form within 3 days
    """
    date_time_before_3_days = timezone.localtime(timezone.now() - timedelta(days=3))
    applications = (
        Application.objects.filter(
            partner__name=PartnerNameConstant.KLOP,
            application_status=ApplicationStatusCodes.FORM_CREATED,
            cdate__date=date_time_before_3_days.date()
        )
        .select_related("customer", "partner")
    )
    if applications:
        for application in applications:
            trigger_partnership_callback.delay(
                application.id,
                application.status, is_notification=True
            )


@task(
    name="send_email_notification_to_user_check_submission_status_task",
    queue="partner_leadgen_global_queue",
)
def send_email_notification_to_user_check_submission_status_task(application_id: int):
    """
    Send notification to user when user in 105 status and not in c Score
    Currently only for Lead gen
    """
    from juloserver.partnership.leadgenb2b.onboarding.services import (
        is_income_in_range_leadgen_partner,
    )
    from juloserver.partnership.services.services import (
        is_income_in_range_agent_assisted_partner,
    )

    logger.info(
        {
            "action": "send_email_notification_to_user_check_submission_status_task",
            "application_id": application_id,
        }
    )
    application = Application.objects.get_or_none(pk=application_id)
    if not application:
        return

    partner = application.partner

    if not partner:
        return

    partnership_config = partner.partnership_config
    if not partnership_config:
        return

    partnership_type = partnership_config.partnership_type
    if not partnership_config.partnership_type:
        return

    if partnership_type.partner_type_name != PartnershipTypeConstant.LEAD_GEN:
        return

    sonic_pass = False
    is_105_status = False
    salary_izi_data = False
    is_c_score = JuloOneService.is_c_score(application)

    if is_c_score:
        return

    sonic_pass = check_iti_repeat(application.id)
    customer_high_score = feature_high_score_full_bypass(application)
    if application.application_status_id == ApplicationStatusCodes.FORM_PARTIAL:
        is_105_status = True

    if not customer_high_score and not sonic_pass:
        salary_izi_data = check_salary_izi_data(application)

    job_type = JobType.objects.get_or_none(job_type=application.job_type)
    is_salaried = job_type.is_salaried if job_type else None
    passes_income_check = salary_izi_data and is_salaried

    is_pass_income_check_and_range = not passes_income_check or (
        passes_income_check
        and (
            not is_income_in_range(application)
            or not is_income_in_range_leadgen_partner(application)
            or not is_income_in_range_agent_assisted_partner(application)
        )
    )

    if not sonic_pass and is_105_status and is_pass_income_check_and_range:
        # send the notification
        notify_user_to_check_submission_status.delay(application.id)
        return

    return


@task(queue="partner_mf_cronjob_queue")
def download_image_from_url_and_upload_to_oss(
    url: str, application_id: int, image_type: str
) -> File:
    """
    For Google Drive URL, only works for sharable file
    """
    logger.info(
        {
            "action": "download_image_from_url_and_upload_to_oss",
            "application_id": application_id,
        }
    )
    application = Application.objects.filter(id=application_id).last()
    if not application:
        raise Exception("Application not exists: {}".format(application_id))

    julo_sentry_client = get_julo_sentry_client()

    if "drive.google" in url:
        regex = "https://drive.google.com/file/d/(.*?)/(.*?)"
        file_id = re.search(regex, url)
        if not file_id:
            raise Exception("Google Drive URL is not valid: {}".format(url))
        file_id = file_id[1]
        google_base_url = "https://docs.google.com/uc?export=download"
        session = requests.Session()
        response = session.get(google_base_url, params={"id": file_id}, stream=True)
    else:
        response = requests.get(url, stream=True)

    content_type = response.headers.get("Content-Type")

    # Adding exclude application/octet-stream because
    # sometimes image generate from 3rd party like AWS use that type PARTNER-1860
    if content_type == "application/octet-stream":
        try:
            image_data = BytesIO(response.content)
            Imagealias.open(image_data)
        except OSError:
            julo_sentry_client.captureException()
            raise Exception("File is not an image: {}".format(url))

    elif "image" not in content_type:
        raise Exception("File is not an image: {}".format(url))

    fp = BytesIO()
    fp.write(response.content)
    image = File(fp)

    partnership_image = PartnershipImage()
    partnership_image.image_type = image_type
    partnership_image.application_image_source = application.id
    partnership_image.product_type = PartnershipImageProductType.MF_CSV_UPLOAD
    partnership_image.save()
    partnership_image.image.save("{}_{}.jpeg".format(application.id, image_type), image)
    upload_partnership_image.delay(partnership_image.id)


@task(queue='partner_leadgen_global_queue')
def agent_assisted_process_pre_upload_user_task(
    upload_async_state_id: int,
    partner_id: int,
) -> None:
    from juloserver.partnership.crm.services import agent_assisted_upload_user_pre_check

    upload_async_state = UploadAsyncState.objects.filter(
        id=upload_async_state_id,
        task_type=UploadAsyncStateType.AGENT_ASSISTED_PRE_CHECK_USER,
        task_status=UploadAsyncStateStatus.WAITING,
    ).first()

    partner = Partner.objects.filter(id=partner_id).last()
    if not upload_async_state or not upload_async_state.file:
        logger.info(
            {
                "action": "agent_assisted_pre_upload_user_check_task_failed",
                "message": "File not found",
                "upload_async_state_id": upload_async_state_id,
            }
        )

        if upload_async_state:
            upload_async_state.update_safely(task_status=UploadAsyncStateStatus.FAILED)

        return

    upload_async_state.update_safely(task_status=UploadAsyncStateStatus.PROCESSING)

    try:
        is_success_all = agent_assisted_upload_user_pre_check(
            upload_async_state, partner
        )
        if is_success_all:
            task_status = UploadAsyncStateStatus.COMPLETED
        else:
            task_status = UploadAsyncStateStatus.PARTIAL_COMPLETED
        upload_async_state.update_safely(task_status=task_status)

    except Exception as e:
        sentry_client = get_julo_sentry_client()
        sentry_client.capture_exceptions()
        upload_async_state.update_safely(task_status=UploadAsyncStateStatus.FAILED)
        logger.exception(
            {
                'module': 'partnership_agent_assisted',
                'action': 'agent_assisted_pre_upload_user_check_task_failed',
                'upload_async_state_id': upload_async_state_id,
                'error': e,
            }
        )


@task(queue='partner_leadgen_global_queue')
def partnership_run_fdc_inquiry_for_registration(
    fdc_inquiry_data: dict, reason, retry_count=0, retry=False
):
    try:
        logger.info(
            {
                "function": "partnership_run_fdc_inquiry_for_registration",
                "action": "call get_and_save_fdc_data",
                "fdc_inquiry_data": fdc_inquiry_data,
                "reason": reason,
                "retry_count": retry_count,
                "retry": retry,
            }
        )
        get_and_save_fdc_data(fdc_inquiry_data, reason, retry)
        return True, retry_count
    except FDCServerUnavailableException:
        logger.error(
            {
                "action": "partnership_run_fdc_inquiry_for_registration",
                "error": "FDC server can not reach",
                "data": fdc_inquiry_data,
                "extra_data": "retry_count={}".format(retry_count),
            }
        )
    except Exception as e:
        sentry_client = get_julo_sentry_client()
        sentry_client.captureException()

        logger.info(
            {
                "action": "partnership_run_fdc_inquiry_for_registration",
                "error": "retry fdc request with error: %(e)s" % {'e': e},
                "data": fdc_inquiry_data,
                "extra_data": "retry_count={}".format(retry_count),
            }
        )

    fdc_retry_feature = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.RETRY_FDC_INQUIRY, category="fdc"
    ).last()

    if not fdc_retry_feature or not fdc_retry_feature.is_active:
        logger.info(
            {
                "action": "partnership_run_fdc_inquiry_for_registration",
                "error": "fdc_retry_feature is not active",
                "data": fdc_inquiry_data,
                "extra_data": "retry_count={}".format(retry_count),
            }
        )
        return False, retry_count

    params = fdc_retry_feature.parameters
    retry_interval_minutes = params['retry_interval_minutes']
    max_retries = params['max_retries']

    if retry_interval_minutes == 0:
        raise JuloException(
            "Parameter retry_interval_minutes: "
            "%(retry_interval_minutes)s can not be zero value "
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
                "action": "partnership_run_fdc_inquiry_for_registration",
                "message": "Retry FDC Inquiry has exceeded the maximum limit",
                "data": fdc_inquiry_data,
                "extra_data": "retry_count={}".format(retry_count),
            }
        )

        return False, retry_count

    retry_count += 1

    logger.info(
        {
            'action': 'partnership_run_fdc_inquiry_for_registration',
            "data": fdc_inquiry_data,
            "extra_data": "retry_count={}|count_down={}".format(retry_count, countdown_seconds),
        }
    )

    partnership_run_fdc_inquiry_for_registration.apply_async(
        (fdc_inquiry_data, reason, retry_count, retry), countdown=countdown_seconds
    )

    return True, retry_count


@task(queue='partner_leadgen_global_queue')
def agent_assisted_scoring_user_data_upload_task(upload_async_state_id: int) -> None:
    from juloserver.partnership.crm.services import (
        agent_assisted_upload_scoring_user_data,
    )

    upload_async_state = UploadAsyncState.objects.filter(
        id=upload_async_state_id,
        task_type=UploadAsyncStateType.AGENT_ASSISTED_SCORING_USER_DATA,
        task_status=UploadAsyncStateStatus.WAITING,
    ).first()

    if not upload_async_state or not upload_async_state.file:
        logger.info(
            {
                "action": "agent_assisted_pre_upload_user_check_task_failed",
                "message": "File not found",
                "upload_async_state_id": upload_async_state_id,
            }
        )

        if upload_async_state:
            upload_async_state.update_safely(task_status=UploadAsyncStateStatus.FAILED)

        return

    upload_async_state.update_safely(task_status=UploadAsyncStateStatus.PROCESSING)

    try:
        is_success_all = agent_assisted_upload_scoring_user_data(upload_async_state)
        if is_success_all:
            task_status = UploadAsyncStateStatus.COMPLETED
        else:
            task_status = UploadAsyncStateStatus.PARTIAL_COMPLETED
        upload_async_state.update_safely(task_status=task_status)

    except Exception as e:
        sentry_client = get_julo_sentry_client()
        sentry_client.capture_exceptions()
        upload_async_state.update_safely(task_status=UploadAsyncStateStatus.FAILED)
        logger.exception(
            {
                'module': 'partnership_agent_assisted',
                'action': 'agent_assisted_upload_scoring_user_data_failed',
                'upload_async_state_id': upload_async_state_id,
                'error': e,
            }
        )


@task(queue='partner_leadgen_global_queue')
def agent_assisted_process_pre_check_fdc_upload_user_task(
    upload_async_state_id: int,
    partner_id: int,
) -> None:
    from juloserver.partnership.crm.services import (
        agent_assisted_upload_user_fdc_pre_check,
    )

    upload_async_state = UploadAsyncState.objects.filter(
        id=upload_async_state_id,
        task_type=UploadAsyncStateType.AGENT_ASSISTED_FDC_PRE_CHECK_USER,
        task_status=UploadAsyncStateStatus.WAITING,
    ).first()

    partner = Partner.objects.filter(id=partner_id).last()
    if not upload_async_state or not upload_async_state.file:
        logger.info(
            {
                "action": "agent_assisted_fdc_pre_upload_user_check_task_failed",
                "message": "File not found",
                "upload_async_state_id": upload_async_state_id,
            }
        )

        if upload_async_state:
            upload_async_state.update_safely(task_status=UploadAsyncStateStatus.FAILED)

        return

    upload_async_state.update_safely(task_status=UploadAsyncStateStatus.PROCESSING)

    try:
        is_success_all = agent_assisted_upload_user_fdc_pre_check(upload_async_state, partner)
        if is_success_all:
            task_status = UploadAsyncStateStatus.COMPLETED
        else:
            task_status = UploadAsyncStateStatus.PARTIAL_COMPLETED
        upload_async_state.update_safely(task_status=task_status)

    except Exception as e:
        sentry_client = get_julo_sentry_client()
        sentry_client.capture_exceptions()
        upload_async_state.update_safely(task_status=UploadAsyncStateStatus.FAILED)
        logger.exception(
            {
                'module': 'partnership_agent_assisted',
                'action': 'agent_assisted_fdc_pre_upload_user_check_task_failed',
                'upload_async_state_id': upload_async_state_id,
                'error': e,
            }
        )


@task(bind=True, queue="partner_leadgen_global_queue", max_retries=3)
def send_email_agent_assisted(
    self, application_id: int, is_reject=False, is_x190=False, set_limit=0
):
    """
    Send email create pin/soft reject to user from agent assisted
    """
    application = Application.objects.filter(pk=application_id).last()
    if not application:
        return

    partner = application.partner
    if not partner:
        return

    skip_uw_application = (
        PartnershipFlowFlag.objects.filter(
            partner=application.partner,
            name=PartnershipProductFlow.AGENT_ASSISTED,
            configs__skip_uw_application_email_pin_creation=True,
        )
        .exists()
    )
    if skip_uw_application:
        send_email_skip_uw_application_agent_assisted(
            application=application, is_reject=is_reject, is_x190=is_x190
        )
        return

    # Check if customer already create pin
    is_pin_created = False
    if pin_services.does_user_have_pin(application.customer.user):
        is_pin_created = True

    if not is_pin_created:
        if settings.ENVIRONMENT != 'prod':
            base_julo_web_url = "https://app-staging1.julo.co.id"
        else:
            base_julo_web_url = settings.JULO_WEB_URL

        jwt = JWTManager(
            user=application.customer.user,
            partner_name=partner.name,
            application_xid=application.application_xid,
            product_id=application.product_line_code,
        )
        user_token = jwt.create_or_update_token(token_type=PartnershipTokenType.ACCESS_TOKEN)

        action_url = '{}/view/create-pin?partner_name={}&token={}'.format(
            base_julo_web_url, partner.name, user_token.token
        )

    else:
        action_url = 'https://go.onelink.me/zOQD/93d068ac'  # Deeplink mobile url

    application.refresh_from_db()
    logger.info(
        {
            "action": "send_email_agent_assisted",
            "application_id": application_id,
            "has_pin": is_pin_created,
            "application_status": application.application_status_id
        }
    )

    try:
        if not is_reject:

            if is_x190:
                template_code = 'email_agent_assisted_loc_approved_agent_190'
                email_sent = get_partnership_email_client().email_loc_approved_agent_assisted(
                    application=application, action_url=action_url, is_pin_created=is_pin_created,
                    set_limit=set_limit
                )
            else:
                template_code = 'email_agent_assisted_create_pin'
                email_sent = get_partnership_email_client().email_create_pin_agent_assisted(
                    application=application, action_url=action_url, is_pin_created=is_pin_created
                )

            EmailHistory.objects.create(
                application=application,
                customer=email_sent.customer,
                sg_message_id=email_sent.headers["X-Message-Id"],
                to_email=email_sent.email_to,
                subject=email_sent.subject,
                message_content=email_sent.message,
                status=str(email_sent.status),
                template_code=template_code,
            )
        else:
            template_code = 'email_agent_assisted_soft_reject'
            email_sent = get_partnership_email_client().email_soft_reject_agent_assisted(
                application=application, action_url=action_url, is_pin_created=is_pin_created
            )

            EmailHistory.objects.create(
                application=application,
                customer=email_sent.customer,
                sg_message_id=email_sent.headers["X-Message-Id"],
                to_email=email_sent.email_to,
                subject=email_sent.subject,
                message_content=email_sent.message,
                status=str(email_sent.status),
                template_code=template_code,
            )

    except Exception as exception_error:
        if isinstance(exception_error, EmailNotSent):
            if self.request.retries < self.max_retries:
                logger.info(
                    {
                        "action": "retry_send_email_agent_assisted",
                        "message": "Retry to send email agent assisted",
                        "application_id": application_id,
                        "application_status": application.application_status_id,
                        "is_reject": is_reject,
                        "is_x190": is_x190,
                        "set_limit": set_limit,
                        "error": str(exception_error)
                    }
                )
                raise self.retry(exc=exception_error, countdown=60)

        logger.exception(
            {
                "action": "failed_send_email_agent_assisted",
                "message": "Failed to send email agent assisted",
                "application_id": application_id,
                "application_status": application.application_status_id,
                "is_reject": is_reject,
                "is_x190": is_x190,
                "set_limit": set_limit,
                "error": str(exception_error)
            }
        )
        raise exception_error


@task(queue="partner_leadgen_global_queue")
def process_sending_email_agent_assisted(application_id: int, is_reject=False, is_x190=False):
    partnership_application_flag = PartnershipApplicationFlag.objects.filter(
        application_id=application_id,
        name=PartnershipPreCheckFlag.APPROVED,
    ).exists()

    logger.info(
        {
            "action": "process_sending_email_agent_assisted",
            "application_id": application_id,
            "is_reject": is_reject,
            "is_x190": is_x190,
            "partnership_application_flag": partnership_application_flag
        }
    )

    if partnership_application_flag:
        send_email_agent_assisted(
            application_id=application_id, is_reject=is_reject,
            is_x190=is_x190, set_limit=0
        )


@task(queue="partner_leadgen_global_queue")
def send_email_106_for_agent_assisted_application(application_id: int):
    application = (
        Application.objects.filter(pk=application_id)
        .values('partner_id', 'customer_id')
        .first()
    )

    application_customer = Customer.objects.filter(id=application['customer_id']).first()

    # Check if customer already create pin
    is_pin_created = pin_services.does_user_have_pin(application_customer.user)

    if is_pin_created:
        filters = {
            'partner': application['partner_id'],
            'name': PartnershipProductFlow.AGENT_ASSISTED,
            'configs__reject_agent_assisted_email__without_create_pin': True,
        }
    else:
        filters = {
            'partner': application['partner_id'],
            'name': PartnershipProductFlow.AGENT_ASSISTED,
            'configs__reject_agent_assisted_email__with_create_pin': True,
        }

    partnership_flow_configs = PartnershipFlowFlag.objects.filter(
        **filters
    ).exists()

    logger.info(
        {
            "action": "send_email_106_for_agent_assisted_application",
            "application_id": application_id,
            "partnership_flow_configs": partnership_flow_configs,
            "configs": "reject_agent_assisted_email",
            "has_pin": is_pin_created
        }
    )

    if partnership_flow_configs:
        process_sending_email_agent_assisted(
            application_id=application_id, is_reject=True, is_x190=False
        )


@task(queue='partner_leadgen_global_queue')
def agent_assisted_process_complete_user_data_update_status_task(
    upload_async_state_id: int,
) -> None:
    from juloserver.partnership.crm.services import (
        agent_assisted_process_complete_user_data_update_status,
    )

    upload_async_state = UploadAsyncState.objects.filter(
        id=upload_async_state_id,
        task_type=UploadAsyncStateType.AGENT_ASSISTED_COMPLETE_DATA_STATUS_UPDATE,
        task_status=UploadAsyncStateStatus.WAITING,
    ).first()
    if not upload_async_state or not upload_async_state.file:
        logger.info(
            {
                "action": "agent_assisted_process_complete_user_data_update_status_task_failed",
                "message": "File not found",
                "upload_async_state_id": upload_async_state_id,
            }
        )

        if upload_async_state:
            upload_async_state.update_safely(task_status=UploadAsyncStateStatus.FAILED)

        return

    upload_async_state.update_safely(task_status=UploadAsyncStateStatus.PROCESSING)

    try:
        is_success_all = agent_assisted_process_complete_user_data_update_status(upload_async_state)
        if is_success_all:
            task_status = UploadAsyncStateStatus.COMPLETED
        else:
            task_status = UploadAsyncStateStatus.PARTIAL_COMPLETED
        upload_async_state.update_safely(task_status=task_status)

    except Exception as e:
        sentry_client = get_julo_sentry_client()
        sentry_client.capture_exceptions()
        upload_async_state.update_safely(task_status=UploadAsyncStateStatus.FAILED)
        logger.exception(
            {
                'module': 'partnership_agent_assisted',
                'action': 'agent_assisted_process_complete_user_data_update_status_task_failed',
                'upload_async_state_id': upload_async_state_id,
                'error': e,
            }
        )


@task(bind=True, name="upload_image_from_url", queue="partner_leadgen_global_queue", max_retries=3)
def upload_partnership_image_from_url(
    self,
    image_url: str,
    image_type: str,
    application_id: int,
    product_type: str = PartnershipImageProductType.LEADGEN,
    upload_to: str = PartnershipUploadImageDestination.PARNTERSHIP_IMAGE_TABLE,
) -> None:
    try:
        from juloserver.partnership.services.services import (
            download_image_byte_from_url,
            process_image_upload_partnership,
        )

        image_byte = download_image_byte_from_url(image_url)

        application = (
            Application.objects.filter(id=application_id).select_related("customer").first()
        )

        if not application:
            raise JuloException("Application id=%s not found" % application_id)

        if upload_to == PartnershipUploadImageDestination.PARNTERSHIP_IMAGE_TABLE:
            partnership_image = PartnershipImage()
            partnership_image.image_type = image_type
            partnership_image.application_image_source = application_id
            partnership_image.product_type = product_type
            partnership_image.save()

            cust_id = str(application.customer.id)
            filename = "%s_%s%s" % (
                partnership_image.image_type,
                str(partnership_image.id),
                '.jpeg',
            )
            image_remote_filepath = "/".join(
                ["cust_" + cust_id, "partnership_image_application", filename]
            )

            upload_file_as_bytes_to_oss(
                settings.OSS_MEDIA_BUCKET, image_byte, image_remote_filepath
            )
            partnership_image.url = image_remote_filepath
            partnership_image.save(update_fields=['url'])

            logger.info(
                {
                    "status": "successfull upload image partnership to oss",
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
                img.save(update_fields=['image_status'])

        elif upload_to == PartnershipUploadImageDestination.IMAGE_TABLE:
            image_obj = Image()
            image_obj.image_type = image_type
            image_obj.image_source = application_id
            image_obj.save()

            logger.info(
                {
                    "status": "successfull upload image partnership to oss",
                    "application_id": image_obj.image_source,
                    "image_type": image_obj.image_type,
                }
            )
            image_data = {
                'file_extension': '.jpeg',
                'image_byte_file': image_byte,
            }
            process_image_upload_partnership(
                image_obj, image_data, thumbnail=False, delete_if_last_image=False
            )
        else:
            error_data = {
                "action": "failed_upload_image_from_url",
                "message": "Failed to upload image, upload_to not defined",
                "type": image_type,
                "application_id": application_id,
                "error": "upload_to {} spesific not defined".format(upload_to),
            }

            logger.exception(error_data)
            return

    except (Exception, JuloException) as exception_error:
        if self.request.retries > self.max_retries:
            error_data = {
                "action": "failed_upload_image_from_url",
                "message": "Failed to upload image",
                "type": image_type,
                "application_id": application_id,
                "error": str(exception_error),
            }

            logger.exception(error_data)
            raise exception_error

        logger.info(
            {
                "action": "retry_upload_upload_partnership_image_from_url",
                "message": "Failed to upload image",
                "application_id": application_id,
                "error": str(exception_error),
            }
        )
        raise self.retry(exc=exception_error, countdown=60)


@task(bind=True, queue="partner_leadgen_global_queue", max_retries=3)
def send_email_skip_uw_application_agent_assisted(
    self, application: Application, is_reject=False, is_x190=False
):
    try:
        logger.info(
            {
                "action": "send_email_skip_uw_application_agent_assisted",
                "application_id": application.id,
                "application_status": application.application_status_id,
                "is_reject": is_reject,
                "is_x190": is_x190,
            }
        )
        email_client = get_partnership_email_client()
        if is_reject:
            template_code = 'email_smartphone_financing_agent_assisted_soft_reject'
            email_sent = (
                email_client.email_reject_smartphone_financing_agent_assisted(
                    application=application
                )
            )

            EmailHistory.objects.create(
                application=application,
                customer=email_sent.customer,
                sg_message_id=email_sent.headers["X-Message-Id"],
                to_email=email_sent.email_to,
                subject=email_sent.subject,
                message_content=email_sent.message,
                status=str(email_sent.status),
                template_code=template_code,
            )
        else:
            if is_x190:
                template_code = 'email_smartphone_financing_agent_assisted_approved'
                email_sent = (
                    email_client.email_approved_smartphone_financing_agent_assisted(
                        application=application
                    )
                )

                EmailHistory.objects.create(
                    application=application,
                    customer=email_sent.customer,
                    sg_message_id=email_sent.headers["X-Message-Id"],
                    to_email=email_sent.email_to,
                    subject=email_sent.subject,
                    message_content=email_sent.message,
                    status=str(email_sent.status),
                    template_code=template_code,
                )

    except Exception as exception_error:
        if isinstance(exception_error, EmailNotSent):
            if self.request.retries < self.max_retries:
                logger.info(
                    {
                        "action": "retry_send_email_skip_uw_application_agent_assisted",
                        "message": "Retry to send email skip uw application agent assisted",
                        "application_id": application.id,
                        "application_status": application.application_status_id,
                        "is_reject": is_reject,
                        "is_x190": is_x190,
                        "error": str(exception_error)
                    }
                )
                raise self.retry(exc=exception_error, countdown=60)

        logger.exception(
            {
                "action": "failed_send_email_skip_uw_application_agent_assisted",
                "message": "Failed to send email skip uw application agent assisted",
                "application_id": application.id,
                "application_status": application.application_status_id,
                "is_reject": is_reject,
                "is_x190": is_x190,
                "error": str(exception_error)
            }
        )
        raise exception_error


@task(queue='partner_leadgen_global_queue')
def product_financing_upload_task(
    upload_async_state_id: int,
    action_type: str,
) -> None:
    from juloserver.partnership.crm.services import (
        product_financing_loan_creation_upload,
        product_financing_loan_disbursement_upload,
        product_financing_lender_approval_upload,
    )

    services_map = {
        ProductFinancingUploadActionType.LOAN_CREATION: {
            'task_type': UploadAsyncStateType.PRODUCT_FINANCING_LOAN_CREATION,
            'service': product_financing_loan_creation_upload,
        },
        ProductFinancingUploadActionType.LOAN_DISBURSEMENT: {
            'task_type': UploadAsyncStateType.PRODUCT_FINANCING_LOAN_DISBURSEMENT,
            'service': product_financing_loan_disbursement_upload,
        },
        ProductFinancingUploadActionType.LOAN_REPAYMENT: {
            'task_type': UploadAsyncStateType.PRODUCT_FINANCING_LOAN_REPAYMENT,
            'service': product_financing_loan_repayment_upload,
        },
        ProductFinancingUploadActionType.LENDER_APPROVAL: {
            'task_type': UploadAsyncStateType.PRODUCT_FINANCING_LENDER_APPROVAL,
            'service': product_financing_lender_approval_upload,
        },
    }

    task_type = services_map[action_type]['task_type']
    upload_async_state = UploadAsyncState.objects.filter(
        id=upload_async_state_id,
        task_type=task_type,
        task_status=UploadAsyncStateStatus.WAITING,
    ).first()

    if not upload_async_state or not upload_async_state.file:
        logger.info(
            {
                "action": "product_financing_upload_task",
                "message": "File not found",
                "upload_async_state_id": upload_async_state_id,
            }
        )

        if upload_async_state:
            upload_async_state.update_safely(task_status=UploadAsyncStateStatus.FAILED)

        return

    upload_async_state.update_safely(task_status=UploadAsyncStateStatus.PROCESSING)

    try:
        is_success_all = services_map[action_type]['service'](upload_async_state)
        if is_success_all:
            task_status = UploadAsyncStateStatus.COMPLETED
        else:
            task_status = UploadAsyncStateStatus.PARTIAL_COMPLETED
        upload_async_state.update_safely(task_status=task_status)

    except Exception as e:
        sentry_client = get_julo_sentry_client()
        sentry_client.capture_exceptions()
        upload_async_state.update_safely(task_status=UploadAsyncStateStatus.FAILED)
        logger.exception(
            {
                'module': 'partnership_product_financing',
                'action': 'product_financing_upload_task_failed',
                'service': services_map[action_type]['service'],
                'upload_async_state_id': upload_async_state_id,
                'error': e,
            }
        )


@task(queue="partner_leadgen_global_queue")
def process_expired_skrtp_gosel():
    now = timezone.localtime(timezone.now()).date()
    date_filter = now - timedelta(days=1)
    partner_loan_requests = PartnerLoanRequest.objects.select_related('loan', 'partner').filter(
        partner__name=PartnerConstant.GOSEL,
        loan__loan_status=LoanStatusCodes.INACTIVE,
        loan__sphp_sent_ts__lte=date_filter,
    )

    for loan_request in partner_loan_requests.iterator():
        update_loan_status_and_loan_history(
            loan_id=loan_request.loan.id,
            new_status_code=LoanStatusCodes.CANCELLED_BY_CUSTOMER,
            change_by_id=loan_request.loan.account_id,
            change_reason="SKRTP Expired",
        )


@task(queue='partner_leadgen_global_queue')
def send_email_skrtp_gosel(
    loan_id,
    interest_rate,
    loan_request_date,
    product_name,
) -> None:
    loan = Loan.objects.filter(id=loan_id).select_related('customer').first()

    loan_xid_str = str(loan.loan_xid)
    now = datetime.now()
    now_str = now.strftime("%Y%m%d%H%M%S")
    token_str = '{}_{}'.format(loan_xid_str, now_str)

    token_bytes = token_str.encode("ascii")
    base64_bytes = base64.b64encode(token_bytes)
    base64_string = base64_bytes.decode("ascii")

    skrtp_link = settings.JULO_WEB_URL + '/skrtp/{}'.format(base64_string)

    partner_loan_request = loan.partnerloanrequest_set.first()
    loan_duration_type = partner_loan_request.loan_duration_type
    tenor_unit = 'Bulan'
    if loan_duration_type == LoanDurationType.DAYS:
        tenor_unit = 'Hari'
    tenor = '{} {}'.format(str(loan.loan_duration), tenor_unit)
    email = loan.customer.email
    subject = "Yuk, Konfirmasi Persetujuan Pinjamanmu"
    template = get_template('email/email_skrtp_link_gosel.html')
    context = {
        "skrtp_link": skrtp_link,
        "fullname": loan.customer.fullname,
        "application_date": format_datetime(loan_request_date, "d MMMM yyyy", locale='id_ID'),
        "loan_amount": '{:,}'.format(loan.loan_disbursement_amount).replace(',', '.'),
        "product_name": product_name,
        "interest": interest_rate,
        "tenor": tenor,
    }
    html_content = template.render(context)
    status, _, headers = get_julo_email_client().send_email(
        subject, html_content, email, settings.EMAIL_FROM
    )
    application = loan.get_application
    message_id = headers['X-Message-Id']
    EmailHistory.objects.create(
        customer=loan.customer,
        application=application,
        to_email=email,
        subject=subject,
        sg_message_id=message_id,
        template_code='email_skrtp_link_gosel',
        status=str(status),
    )

    partner_loan_request = PartnerLoanRequest.objects.filter(loan=loan_id).last()
    partner_loan_request.skrtp_link = skrtp_link
    partner_loan_request.save(update_fields=["skrtp_link"])

    loan.sphp_sent_ts = timezone.localtime(now)
    loan.save(update_fields=["sphp_sent_ts"])


@task(queue='partner_leadgen_global_queue')
def process_checking_mandatory_document_at_120(application_id: int) -> None:
    application = Application.objects.filter(id=application_id).select_related("partner").last()
    if not application:
        logger.error(
            {
                "action": "agent_assisted_process_checking_mandatory_document",
                "message": "application not found",
                "application": application_id,
            }
        )
        return

    if not application.partner:
        logger.error(
            {
                "action": "agent_assisted_process_checking_mandatory_document",
                "message": "partner not found",
                "application_status": str(application.status),
                "application": application.id,
            }
        )
        return

    if application.application_status == ApplicationStatusCodes.DOCUMENTS_VERIFIED:
        logger.error(
            {
                "action": "agent_assisted_process_checking_mandatory_document",
                "message": "application already 121 ",
                "application_status": str(application.status),
                "application": application.id,
            }
        )
        return

    partner_name = application.partner.name
    paystub_category = {PartnershipImageType.PAYSTUB, PartnershipImageType.PAYSTUB_OPS}
    is_have_paystub_mandatory_document = Image.objects.filter(
        image_source=application.id, image_type__in=paystub_category
    ).exists()
    if is_have_paystub_mandatory_document:
        new_status_code = ApplicationStatusCodes.SCRAPED_DATA_VERIFIED
        logger.info(
            {
                "action": "agent_assisted_process_checking_mandatory_document",
                "message": "found document paystub, start move application from 120 to 121",
                "old_application_status": str(application.status),
                "new_status_code": new_status_code,
                "application": application.id,
            }
        )
        process_application_status_change(
            application.id,
            new_status_code,
            change_reason='customer_triggered',
        )
        return

    if not is_have_paystub_mandatory_document and partner_name == PartnerConstant.GOSEL:
        new_status_code = ApplicationStatusCodes.SCRAPED_DATA_VERIFIED
        logger.info(
            {
                "action": "agent_assisted_process_checking_mandatory_document",
                "message": "bypass to 121 For partner gojektsel",
                "old_application_status": str(application.status),
                "new_status_code": new_status_code,
                "application": application.id,
            }
        )
        process_application_status_change(
            application.id,
            new_status_code,
            change_reason='customer_triggered',
        )
        return

    logger.info(
        {
            "action": "agent_assisted_process_checking_mandatory_document",
            "message": "can't found document paystub, stay at status 120",
            "application_status": str(application.status),
            "application": application.id,
        }
    )


@task(
    bind=True,
    name="async_process_partnership_application_binary_pre_check",
    queue="partner_leadgen_global_queue",
    max_retries=3
)
def async_process_partnership_application_binary_pre_check(
    self, application_id: int,
) -> None:
    from juloserver.partnership.crm.services import partnership_application_binary_pre_check

    application = Application.objects.filter(id=application_id).last()
    partnership_application_flag = PartnershipApplicationFlag.objects.filter(
        application_id=application_id
    ).last()
    flag_name = partnership_application_flag.name

    try:
        partnership_application_binary_pre_check(application, flag_name)
    except (Exception, JuloException) as exception_error:
        if self.request.retries > self.max_retries:
            error_data = {
                "retries": self.request.retries,
                "max_retries": self.max_retries,
                "action": "failed_async_process_partnership_application_binary_pre_check",
                "message": "failed to process binary pre check",
                "flag_name": flag_name,
                "application_id": application_id,
                "error": str(exception_error),
            }

            logger.exception(error_data)
            raise exception_error

        if (flag_name != PartnershipPreCheckFlag.PENDING_CREDIT_SCORE_GENERATION):
            pending_score = PartnershipPreCheckFlag.PENDING_CREDIT_SCORE_GENERATION
            partnership_application_flag.update_safely(name=pending_score)

        logger.info(
            {
                "retries": self.request.retries,
                "max_retries": self.max_retries,
                "action": "retry_async_process_partnership_application_binary_pre_check",
                "message": "failed to process binary pre check",
                "flag_name": flag_name,
                "application_id": application_id,
                "error": str(exception_error),
            }
        )
        raise self.retry(exc=exception_error, countdown=1)


@task(queue="partner_leadgen_global_queue")
def linkaja_handle_disbursement_failed():
    from juloserver.loan.services.sphp import cancel_loan

    link_aja_partner = Partner.objects.filter(name=PartnerNameConstant.LINKAJA).first()
    loans = Loan.objects.filter(
        customer__application__partner=link_aja_partner,
        customer__application__application_status_id=ApplicationStatusCodes.LOC_APPROVED,
        loan_status=LoanStatusCodes.DISBURSEMENT_FAILED_ON_PARTNER_SIDE,
    )
    if not loans:
        logger.info(
            {
                "action": "linkaja_handle_disbursement_failed",
                "status": "failed",
                "message": "no linkaja loan_ids need to be updated",
            }
        )
        return
    success_loan_ids = []
    for loan in loans.iterator():
        cancel_loan(loan)
        success_loan_ids.append(loan.id)

    logger.info(
        {
            "action": "linkaja_handle_disbursement_failed",
            "status": "success",
            "message": "linkaja loan_ids {} updated successfully".format(success_loan_ids),
        }
    )


@task(queue="partner_leadgen_global_queue")
def partnership_application_status_change_async_process(
    application_id, new_status_code, change_reason, note=None
):
    logger.info(
        {
            "action": "partnership_application_status_change_async_process",
            "status": "start",
            "application_id": application_id,
            "new_status_code": new_status_code,
            "change_reason": change_reason,
            "note": note,
        }
    )
    try:
        process_application_status_change(
            application_id,
            new_status_code,
            change_reason=change_reason,
            note=note,
        )
    except Exception as e:
        logger.error(
            {
                "action": "partnership_application_status_change_async_process",
                "status": "errors",
                "message": str(e),
            }
        )


@task(queue='partner_leadgen_global_queue')
def leadgen_send_email_otp_token_register(email: str, otp_id: int):
    # ledgen old version
    otp_request = OtpRequest.objects.get(pk=otp_id)
    subject = "Ini Kode OTP Kamu"
    template = "email/leadgen_standard_otp_request_email.html"
    target_email = email
    cs_email = "cs@julo.co.id"

    context = {
        'banner_url': settings.EMAIL_STATIC_FILE_PATH
        + 'banner-leadgen-standard-otp-request-email.png',
        'full_name': '',
        'otp_token': otp_request.otp_token,
        'play_store': settings.EMAIL_STATIC_FILE_PATH + 'google-play-badge.png',
        'ojk_icon': settings.EMAIL_STATIC_FILE_PATH + 'ojk.png',
        'afpi_icon': settings.EMAIL_STATIC_FILE_PATH + 'afpi.png',
        'afj_icon': settings.EMAIL_STATIC_FILE_PATH + 'afj.png',
        'cs_email': cs_email,
        'cs_phone': "021-5091 9034 | 021-5091 9035",
        'cs_image': settings.EMAIL_STATIC_FILE_PATH + 'customer_service_icon.png',
        'mail_icon': settings.EMAIL_STATIC_FILE_PATH + 'ic-mail.png',
        'phone_icon': settings.EMAIL_STATIC_FILE_PATH + 'ic-phone.png',
    }
    msg = render_to_string(template, context)
    email_to = target_email

    # Process send email
    status, body, headers = get_partnership_email_client().send_email(
        subject,
        msg,
        email_to,
        email_from=cs_email,
        email_cc=None,
        name_from="JULO",
        reply_to=cs_email,
    )

    email_history = EmailHistory.objects.create(
        status=status,
        sg_message_id=headers['X-Message-Id'],
        to_email=target_email,
        subject=subject,
        message_content=msg,
        template_code="leadgen_standard_otp_request_register",
    )

    # Save email history to otp request
    otp_request.update_safely(email_history=email_history)

    logger.info(
        "email_otp_history_created|email={}, otp_request_id={}, "
        "email_history_id={}".format(target_email, otp_id, email_history.id)
    )


@task(queue='partner_leadgen_global_queue')
def fill_partner_application():
    """
    <<< PARTNER-4329 6 January 2025 >>>
    covered partner (nex, ayokenalin, cermati)
    This function is for filling the partner id, controlled by the feature setting
    forced_filled_partner_config.
    this feature setting to control which partner will be forced filled, if the partner is not
    in the list that partner will not be forced to fill the partner id.
    every application that forced to be filled will have partnership_application_flag
    => force_filled_partner_id

    this will cover application with partner referral code or partner onelink
    """
    feature_setting = PartnershipFeatureSetting.objects.get_or_none(
        feature_name=PartnershipFeatureNameConst.FORCE_FILLED_PARTNER_CONFIG, is_active=True
    )
    if not feature_setting:
        logger.info(
            {
                'action': 'partnership fill_partner_application',
                'message': 'feature setting not found',
            }
        )
        return

    list_null_partner_application = AnaPartnershipNullPartner.objects.all()
    if list_null_partner_application.count() == 0:
        logger.info(
            {
                'action': 'partnership fill_partner_application',
                'message': 'no data need to be runned',
            }
        )
        return

    mapped_applications = {}
    for null_partner_data in list_null_partner_application.iterator():
        mapped_applications[
            null_partner_data.application_id
        ] = null_partner_data.supposed_partner_id

    workflow = Workflow.objects.get_or_none(name=WorkflowConst.JULO_ONE)
    applications = Application.objects.select_related('partner').filter(
        workflow=workflow, partner_id__isnull=True, id__in=list(mapped_applications.keys())
    )

    if not applications:
        logger.info(
            {
                'action': 'partnership fill_partner_application',
                'message': 'no data need to be runned',
            }
        )
        return

    registered_partner_ids = feature_setting.parameters.get('registered_partner_ids')
    if not registered_partner_ids:
        logger.info(
            {
                'action': 'partnership fill_partner_application',
                'message': 'registered_partner_ids is not filled on feature setting',
            }
        )
        return

    logger.info(
        {
            'action': 'partnership fill_partner_application',
            'data': applications.values_list('id', flat=True),
            'total_data': applications.count(),
            'message': 'start force filling partner to the application',
        }
    )

    mapped_queried_partner = {}
    updated_application = []
    application_field_change = []
    partnership_application_flag = []
    for application in applications.iterator():
        supposed_partner_id = mapped_applications.get(application.id, None)
        if not supposed_partner_id:
            continue
        if supposed_partner_id not in registered_partner_ids:
            logger.info(
                {
                    'action': 'partnership fill_partner_application',
                    'application_id': application.id,
                    'supposed_partner_id': supposed_partner_id,
                    'message': 'partner is not registered, please add it to feature setting',
                }
            )
            continue

        partner = mapped_queried_partner.get(supposed_partner_id, None)
        if not partner:
            partner = Partner.objects.get_or_none(id=supposed_partner_id)
            mapped_queried_partner[supposed_partner_id] = partner

        if not partner:
            logger.info(
                {
                    'action': 'partnership fill_partner_application',
                    'application_id': application.id,
                    'supposed_partner_id': supposed_partner_id,
                    'message': 'partner not found',
                }
            )
            continue

        old_value = application.partner_id
        application.partner_id = supposed_partner_id
        application.udate = datetime.now()
        updated_application.append(application)
        application_field_change.append(
            ApplicationFieldChange(
                application=application,
                field_name="partner_id",
                old_value=old_value,
                new_value=application.partner_id,
            )
        )
        application_id = application.id
        partnership_application_flag.append(
            PartnershipApplicationFlag(
                application_id=application_id,
                name=PartnershipFlag.FORCE_FILLED_PARTNER_ID,
            )
        )

    with transaction.atomic():
        PartnershipApplicationFlag.objects.bulk_create(partnership_application_flag, batch_size=100)
        ApplicationFieldChange.objects.bulk_create(application_field_change, batch_size=100)
        bulk_update(updated_application, update_fields=['partner_id', 'udate'], batch_size=100)

    logger.info(
        {
            'action': 'partnership fill_partner_application',
            'total_data': len(updated_application),
            'message': 'finish force filling partner to the application',
        }
    )


@task(queue="partner_mf_global_queue")
def mf_partner_sign_document(digisign_document_id):
    from juloserver.digisign.tasks import (
        generate_filename,
        generate_pdf,
        get_agreement_template,
        get_signature_position,
        prepare_request_structs,
        remove_temporary_file_path,
        update_digisign_document,
    )

    digisign_document = DigisignDocument.objects.get(pk=digisign_document_id)
    loan = Loan.objects.get(pk=digisign_document.document_source)
    application = loan.account.get_active_application()
    product_line_code = application.product_line_code
    body = get_agreement_template(loan.id)
    filename = generate_filename(loan)
    pos_x, pos_y, sign_page = get_signature_position(application)
    document_detail = prepare_request_structs(digisign_document, filename, pos_x, pos_y, sign_page)
    file_path = generate_pdf(body, filename)
    signer_xid = loan.customer.customer_xid
    try:
        is_request_success, response_data = partnership_sign_with_digisign(
            digisign_document, signer_xid, file_path, document_detail, product_line_code
        )
    except Exception as error:
        is_request_success = False
        response_data = {'status': SigningStatus.FAILED, 'error': str(error)}
    finally:
        remove_temporary_file_path(file_path)

    update_digisign_document(is_request_success, digisign_document, response_data)
    if not is_request_success:
        logger.error(
            {
                'action_view': 'partnership.tasks.mf_partner_sign_document',
                'loan_id': loan.id,
                'errors': response_data['error'],
            }
        )
        return


@task(queue="partner_mf_global_queue")
def partnership_register_digisign_task(application_id):
    from juloserver.digisign.exceptions import (
        DigitallySignedRegistrationException,
    )
    from juloserver.partnership.services.digisign import partnership_register_digisign

    application = Application.objects.get(id=application_id)
    try:
        partnership_register_digisign(application)
    except DigitallySignedRegistrationException:
        logger.error(
            {
                'action': 'partnership_register_digisign_task',
                'message': 'Application already registered: {}'.format(application_id),
            }
        )
        raise


@task(queue="partner_mf_global_queue")
def mf_partner_process_sign_document(loan_id: int):
    from juloserver.digisign.tasks import initial_record_digisign_document
    from juloserver.partnership.services.digisign import is_eligible_for_partnership_sign_document

    loan = Loan.objects.filter(pk=loan_id).last()
    if not loan:
        logger.error(
            {
                'action': 'mf_partner_process_sign_document',
                'message': 'Loan not found: {}'.format(loan_id),
            }
        )
        return

    try:
        # trigger digisign service for sign_document
        if is_eligible_for_partnership_sign_document(loan):
            digisign_document = initial_record_digisign_document(loan.id)
            mf_partner_sign_document(digisign_document.id)

    except Exception as e:
        logger.error(
            {
                'action': 'mf_partner_process_sign_document',
                'loan_id': loan_id,
                'error': e,
            }
        )
        return


@task(queue="partnership_global")
def partnership_trigger_process_validate_bank(application_id):
    from juloserver.disbursement.models import BankNameValidationLog, NameBankValidation
    from juloserver.disbursement.constants import NameBankValidationStatus
    from juloserver.julo.services2.client_paymet_gateway import ClientPaymentGateway

    application = Application.objects.filter(id=application_id).last()
    if not application:
        logger.error(
            {
                'action': 'partnership_trigger_process_validate_bank',
                'message': 'application not found',
                'application_id': application_id,
            }
        )
        return

    name_bank_validation_id = application.name_bank_validation_id
    validation = NameBankValidation.objects.get_or_none(pk=name_bank_validation_id)
    if not validation or validation.validation_status != NameBankValidationStatus.SUCCESS:

        bank = BankManager.get_by_name_or_none(application.bank_name)
        if not bank:
            logger.error(
                {
                    'action': 'partnership_trigger_process_validate_bank',
                    'message': 'bank {} not found'.format(application.bank_name),
                    'application_id': application_id,
                }
            )
            return

        try:
            payload = {
                "bank_account": application.bank_account_number,
                "bank_id": bank.id,
                "bank_account_name": application.name_in_bank,
            }
            client = ClientPaymentGateway(
                client_id=settings.PARTNERSHIP_PAYMENT_GATEWAY_CLIENT_ID,
                api_key=settings.PARTNERSHIP_PAYMENT_GATEWAY_API_KEY,
            )
            with transaction.atomic():
                name_bank_validation = NameBankValidation.objects.create(
                    bank_code=bank.bank_code,
                    account_number=payload.get('bank_account'),
                    name_in_bank=payload.get('bank_account_name'),
                    mobile_phone=application.mobile_phone_1,
                    method='PG',  # set method using payment gateway(PG)
                )
                update_fields = [
                    'bank_code',
                    'account_number',
                    'name_in_bank',
                    'mobile_phone',
                    'method',
                ]
                name_bank_validation.create_history('create', update_fields)
                update_fields_for_log_name_bank_validation = [
                    'validation_status',
                    'validated_name',
                    'reason',
                ]

                name_bank_validation_id = name_bank_validation.id  # new name_bank_validation_id
                application.update_safely(name_bank_validation_id=name_bank_validation_id)
                result = client.verify_bank_account(payload)
                is_http_request_success = result.get('success')
                data = result.get('data')
                reason = None

                if is_http_request_success:  # handle status 200
                    validation_result_data = data.get('validation_result')
                    status = validation_result_data.get('status')
                    bank_account_info = validation_result_data.get('bank_account_info')
                    reason = validation_result_data.get('message')
                    if status == 'success':
                        name_bank_validation.validation_status = NameBankValidationStatus.SUCCESS
                        name_bank_validation.validated_name = bank_account_info.get(
                            'bank_account_name'
                        )
                        application.update_safely(
                            bank_account_number=bank_account_info.get('bank_account'),
                            name_in_bank=bank_account_info.get('bank_account_name'),
                        )
                    else:
                        # case if validation_result != success
                        name_bank_validation.validation_status = NameBankValidationStatus.FAILED
                else:
                    # case if error 400, 401, 429, 500
                    reason = result.get('errors')[0]
                    name_bank_validation.validation_status = NameBankValidationStatus.FAILED

                logger.info(
                    {
                        'action': 'partnership_trigger_process_validate_bank',
                        'is_http_request_success': is_http_request_success,
                        'application_id': application_id,
                        'error': result.get('errors'),
                    }
                )

                name_bank_validation.reason = reason
                name_bank_validation.save(update_fields=update_fields_for_log_name_bank_validation)
                name_bank_validation.create_history(
                    'update_status', update_fields_for_log_name_bank_validation
                )
                name_bank_validation.refresh_from_db()
                # create name_bank_validation_log
                name_bank_validation_log = BankNameValidationLog()
                name_bank_validation_log.validated_name = name_bank_validation.name_in_bank
                name_bank_validation_log.account_number = name_bank_validation.account_number
                name_bank_validation_log.method = name_bank_validation.method
                name_bank_validation_log.application = application
                name_bank_validation_log.reason = reason
                name_bank_validation_log.validation_status = name_bank_validation.validation_status
                name_bank_validation_log.validated_name = name_bank_validation.validated_name
                name_bank_validation_log.save()
            return

        except Exception as exception_error:
            sentry_client = get_julo_sentry_client()
            sentry_client.captureException()
            logger.error(
                {
                    'action': 'partnership_trigger_process_validate_bank',
                    'message': str(exception_error),
                    'application_id': application_id,
                }
            )
            return
    else:
        logger.info(
            {
                'action': 'partnership_trigger_process_validate_bank',
                'message': 'validation_status already success',
                'application_id': application_id,
            }
        )
        application.update_safely(
            bank_account_number=validation.account_number,
            name_in_bank=validation.validated_name,
        )
        return


@task(queue="partnership_global")
def proceed_cashin_confirmation_linkaja_task(loan_id: int) -> bool:
    from juloserver.partnership.clients.tasks import task_check_transaction_linkaja
    from juloserver.partnership.services.web_services import cashin_confirmation_linkaja

    partnership_transaction = (
        PartnershipTransaction.objects.filter(loan_id=loan_id)
        .only("id", "partner", "loan")
        .order_by("-id")
        .first()
    )

    if (
        partnership_transaction
        and partnership_transaction.partner.name == PartnerNameConstant.LINKAJA
    ):
        loan = partnership_transaction.loan
        cashin_confirmation_linkaja(loan, partnership_transaction.partner)
        task_check_transaction_linkaja.delay(loan.id, partnership_transaction.id)


@task(queue="partner_leadgen_global_queue")
def rerun_leadgen_stuck_105():
    from juloserver.partnership.scripts.fdc_webapp_webview_stuck_105 import (
        check_application_stuck_105,
    )

    is_feature_setting_active = PartnershipFeatureSetting.objects.filter(
        feature_name=PartnershipFeatureNameConst.LEADGEN_WEBAPP_CONFIG_RESUME_STUCK_105,
        is_active=True,
    ).exists()

    if not is_feature_setting_active:
        logger.info(
            {
                "action": "rerun_leadgen_stuck_105",
                "message": "skip rerun_leadgen_stuck_105, feature_setting is off",
            }
        )
        return

    logger.info(
        {
            "action": "rerun_leadgen_stuck_105",
            "message": "start check_application_stuck_105",
        }
    )
    check_application_stuck_105()


@task(queue='partnership_global')
def upload_image_partnership(image, image_data=None, thumbnail=True, deleted_if_last_image=False):
    from juloserver.partnership.services.services import process_image_upload_partnership

    process_image_upload_partnership(image, image_data, thumbnail, deleted_if_last_image)
