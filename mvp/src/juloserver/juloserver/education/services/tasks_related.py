import logging
import pdfkit
import tempfile
import os

from babel.numbers import format_number
from babel.dates import format_date
from django.conf import settings
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

from juloserver.education.constants import EducationConst

sentry_client = get_julo_sentry_client()
logger = logging.getLogger(__name__)


def get_education_invoice_template(education_transaction, template, is_for_email=False):
    if not education_transaction:
        raise Exception
    image_url = settings.STATIC_ALICLOUD_BUCKET_URL + 'education/'
    loan = education_transaction.loan
    student_register = education_transaction.student_register
    school = student_register.school
    bank_account_destination = student_register.bank_account_destination
    disbursement = Disbursement.objects.get_or_none(pk=loan.disbursement_id)
    context = {
        'category_product_name': loan.transaction_method.fe_display_name,
        'image_url': image_url,
        'reference_id': get_first_12_digits(string=disbursement.reference_id),
        'transaction_date': format_date(
            timezone.localtime(loan.fund_transfer_ts), "d MMM yyyy", locale='id_ID'
        ),
        'school_name': school.name,
        'bank_name': bank_account_destination.bank.bank_name,
        'account_number': bank_account_destination.name_bank_validation.account_number,
        'student_fullname': student_register.student_fullname,
        'note': student_register.note,
        'amount': format_number(loan.loan_disbursement_amount, locale='id_ID'),
    }

    if is_for_email:
        context['customer_fullname'] = loan.customer.fullname

    return render_to_string(template, context=context)


def generate_education_invoice(education_transaction):
    if not education_transaction:
        raise Exception

    template = get_education_invoice_template(
        education_transaction,
        EducationConst.TEMPLATE_PATH + 'invoice_pdf.html',
    )

    loan = education_transaction.loan
    student_register = education_transaction.student_register
    filename = 'invoice_{}{}.pdf'.format(student_register.school_id, loan.loan_xid)
    local_path = os.path.join(tempfile.gettempdir(), filename)

    try:
        pdfkit.from_string(template, local_path, options=get_default_pdf_options(zoom=1.5))
    except Exception as e:
        logger.info({'action': 'generate_education_invoice', 'error': str(e)})
        sentry_client.captureException()
        raise e

    document = Document.objects.create(
        document_source=loan.id,
        document_type=EducationConst.DOCUMENT_TYPE,
        filename=filename,
        loan_xid=loan.loan_xid,
    )

    upload_document(document.id, local_path, is_loan=True)


def send_email_education_invoice(education_transaction):
    if not education_transaction:
        raise Exception

    email_client = get_julo_email_client()
    template = get_education_invoice_template(
        education_transaction,
        EducationConst.TEMPLATE_PATH + 'invoice_email.html',
        is_for_email=True,
    )

    loan = education_transaction.loan
    account = loan.account
    application = loan.get_application
    customer = account.customer

    document = Document.objects.filter(
        document_source=loan.id,
        document_type=EducationConst.DOCUMENT_TYPE,
    ).last()

    email_to = customer.email or application.email

    subject = "Bukti Pembayaran SPP Melalui JULO"
    _, _, headers = email_client.send_email(
        subject,
        template,
        email_to,
        attachment_dict=get_education_invoice_attachment(document, education_transaction),
        email_from=EmailDeliveryAddress.CS_JULO,
        name_from='JULO',
        content_type="text/html",
    )

    template_code = EducationConst.EMAIL_TEMPLATE_CODE
    logger.info(
        {'action': 'send_email_education_invoice', 'email': email_to, 'template': template_code}
    )

    EmailHistory.objects.create(
        customer=customer,
        sg_message_id=headers["X-Message-Id"],
        to_email=email_to,
        subject=subject,
        application=application,
        message_content=template,
        template_code=template_code,
    )


def get_education_invoice_attachment(document, education_transaction):
    if not education_transaction:
        raise Exception

    template = get_education_invoice_template(
        education_transaction,
        EducationConst.TEMPLATE_PATH + 'invoice_pdf.html',
    )
    filename = document.filename
    pdf_content = get_pdf_content_from_html(template, filename)
    attachment_dict = {"content": pdf_content, "filename": filename, "type": "application/pdf"}

    # Delete local document
    local_path = os.path.join(tempfile.gettempdir(), filename)
    if os.path.isfile(local_path):
        logger.info(
            {
                "action": "get_education_invoice_attachment",
                "document_path": local_path,
                "document_source": document.document_source,
            }
        )
        os.remove(local_path)
    return attachment_dict
