import logging
import pdfkit
import tempfile
import os

from babel.numbers import format_number
from babel.dates import format_date
from django.utils import timezone
from django.template.loader import render_to_string

from juloserver.account.utils import get_first_12_digits
from juloserver.disbursement.models import Disbursement
from juloserver.julo.constants import EmailDeliveryAddress
from juloserver.julo.clients import (
    get_julo_sentry_client,
    get_julo_email_client,
)
from juloserver.julo.models import (
    Document,
    EmailHistory,
)
from juloserver.julo.services import get_pdf_content_from_html
from juloserver.julo.tasks import upload_document
from juloserver.loan.utils import get_default_pdf_options
from juloserver.healthcare.constants import HealthcareConst

sentry_client = get_julo_sentry_client()
logger = logging.getLogger(__name__)


def get_healthcare_invoice_template(healthcare_user, loan, template_name):
    bank_reference_number = None
    disbursement = Disbursement.objects.get_or_none(pk=loan.disbursement_id)
    if disbursement and disbursement.reference_id:
        bank_reference_number = get_first_12_digits(string=disbursement.reference_id)

    context = {
        'customer_fullname_with_title': loan.get_application.fullname_with_title,
        'product_display_name': loan.transaction_method.fe_display_name,
        'product_foreground_icon_url': loan.transaction_method.foreground_icon_url,
        'bank_reference_number': bank_reference_number,
        'transaction_date': format_date(
            timezone.localtime(loan.fund_transfer_ts), "d MMM yyyy", locale='id_ID'
        ),
        'healthcare_platform_name': healthcare_user.healthcare_platform.name,
        'bank_name': loan.bank_account_destination.bank.bank_name_frontend,
        'account_number': loan.bank_account_destination.name_bank_validation.account_number,
        'healthcare_user_fullname': healthcare_user.fullname if healthcare_user.fullname else '-',
        'amount': format_number(loan.loan_disbursement_amount, locale='id_ID'),
    }

    return render_to_string(HealthcareConst.TEMPLATE_PATH + template_name, context=context)


def generate_healthcare_invoice(healthcare_user, loan):
    template = get_healthcare_invoice_template(healthcare_user, loan, 'invoice_pdf.html')

    filename = 'invoice_{}{}.pdf'.format(healthcare_user.id, loan.loan_xid)
    local_path = os.path.join(tempfile.gettempdir(), filename)

    try:
        pdfkit.from_string(template, local_path, options=get_default_pdf_options(zoom=1.5))
    except Exception as e:
        logger.info({'action': 'generate_healthcare_invoice', 'error': str(e)})
        sentry_client.captureException()
        raise e

    document = Document.objects.create(
        document_source=loan.id,
        document_type=HealthcareConst.DOCUMENT_TYPE_INVOICE,
        filename=filename,
        loan_xid=loan.loan_xid,
    )

    upload_document(document.id, local_path, is_loan=True)


def send_email_healthcare_invoice(healthcare_user, loan):
    email_client = get_julo_email_client()

    application = loan.get_application
    customer = loan.customer
    email_to = customer.email or application.email
    subject = "Ini Bukti Bayar Transaksi Biaya Kesehatan Kamu, Ya!"
    email_content = get_healthcare_invoice_template(healthcare_user, loan, 'invoice_email.html')
    pdf_content = get_healthcare_invoice_template(healthcare_user, loan, 'invoice_pdf.html')
    template_code = HealthcareConst.EMAIL_TEMPLATE_CODE
    document = Document.objects.filter(
        document_source=loan.id,
        document_type=HealthcareConst.DOCUMENT_TYPE_INVOICE,
    ).last()

    _, _, headers = email_client.send_email(
        subject,
        email_content,
        email_to,
        attachment_dict={
            "content": get_pdf_content_from_html(
                pdf_content, document.filename, options=get_default_pdf_options(zoom=1.5)
            ),
            "filename": document.filename,
            "type": "application/pdf",
        },
        email_from=EmailDeliveryAddress.CS_JULO,
        name_from='JULO',
        content_type="text/html",
    )

    logger.info(
        {'action': 'send_email_healthcare_invoice', 'email': email_to, 'template': template_code}
    )

    EmailHistory.objects.create(
        customer=customer,
        sg_message_id=headers["X-Message-Id"],
        to_email=email_to,
        subject=subject,
        application=application,
        message_content=email_content,
        template_code=template_code,
    )
