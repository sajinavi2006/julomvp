from builtins import object
import logging
import base64

from babel.dates import format_date
from django.template.loader import render_to_string

from juloserver.account_payment.services.earning_cashback import get_paramters_cashback_new_scheme
from juloserver.julo.constants import EmailDeliveryAddress
from juloserver.loan.services.agreement_related import get_julo_loan_agreement_template
from django.conf import settings
from juloserver.julo.models import (
    Document,
    PaymentMethod,
    PaymentMethodLookup,
)
from juloserver.followthemoney.services import get_skrtp_or_sphp_pdf
from juloserver.julo.utils import (
    get_file_from_oss,
    display_rupiah_skrtp,
)
from datetime import timedelta

logger = logging.getLogger(__name__)


class LoanEmailClient(object):
    def get_pdf_sphp(self, loan, application):
        (
            body,
            agreement_type,
            lender_signature,
            borrower_signature,
        ) = get_julo_loan_agreement_template(loan.id)

        # application are set to none so loan_xid are used
        document = get_skrtp_or_sphp_pdf(loan, None)

        if not document:
            logger.info(
                {
                    'action': 'get_pdf_sphp',
                    'error': 'sphp/skrtp document not found and cannot be created',
                    'loan_id': loan.id,
                    'agreement_type': agreement_type,
                }
            )

        document_stream = get_file_from_oss(settings.OSS_MEDIA_BUCKET, document.url)
        content = base64.b64encode(document_stream.read()).decode('utf-8')

        attachment_dict = {
            "content": content,
            "filename": document.filename,
            "type": "application/pdf",
        }
        return attachment_dict, agreement_type, "text/html"

    def get_txt_signature(self, loan, agreement_type, customer):
        return_value = []
        document = Document.objects.filter(
            document_source=loan.id,
            document_type="{}_julo".format(agreement_type),
            key_id__isnull=False,
        ).last()
        if not document:
            return return_value

        return_value.append(
            {
                "content": base64.b64encode(bytes(document.hash_digi_sign, 'utf-8')).decode(),
                "filename": "digital_signature.txt",
                "type": "text/plain",
            }
        )
        return return_value

    def email_sphp(self, loan, mail_type, template):
        application = loan.get_application
        customer = loan.customer
        first_payment = loan.payment_set.order_by('payment_number').first()
        primary_payment_method = PaymentMethod.objects.filter(
            customer=customer,
            is_primary=True,
        ).first()
        method_lookup = PaymentMethodLookup.objects.filter(
            name=primary_payment_method.payment_method_name
        ).first()

        _, cashback_percentage_mapping = get_paramters_cashback_new_scheme()
        cashback_counter = loan.account.cashback_counter_for_customer
        cashback_percentage = cashback_percentage_mapping.get(str(cashback_counter))

        context = {
            'fullname_with_title': application.fullname_with_title,
            'loan_amount_display': display_rupiah_skrtp(loan.loan_amount),
            'transaction_method_foreground_icon': loan.transaction_method.foreground_icon_url,
            'transaction_method_fe_display_name': loan.transaction_method.fe_display_name,
            'first_payment_amount_display': display_rupiah_skrtp(first_payment.due_amount),
            'first_payment_due_date': format_date(
                date=first_payment.due_date,
                format='d MMM yyyy',
                locale='id_ID',
            ),
            'image_prefix_url': settings.STATIC_ALICLOUD_BUCKET_URL,
            'payment_method_logo_url': method_lookup.image_logo_url if method_lookup else None,
            'payment_method_name': primary_payment_method.payment_method_name,
            'payment_method_virtual_account': primary_payment_method.virtual_account,
            'cashback_counter': cashback_counter,
            'cashback_percentage': cashback_percentage,
            'cashback_due_date_format': format_date(
                date=first_payment.due_date - timedelta(days=2),
                format='dd/MM/yyyy',
                locale='id_ID',
            ),
        }
        email_from = EmailDeliveryAddress.CS_JULO
        name_from = 'JULO'
        reply_to = ''
        msg = render_to_string(template, context)
        email_to = customer.email if customer.email else application.email
        pdf_attachment, agreement_type, content_type = self.get_pdf_sphp(loan, application)
        # digital_signature attachment will be disabled
        # txt_attachment = self.get_txt_signature(loan, agreement_type, customer)
        # txt_attachment.extend([pdf_attachment])
        file_attachment = [pdf_attachment]
        subject = mail_type
        status, body, headers = self.send_email(
            subject,
            msg,
            email_to,
            email_from=email_from,
            email_cc=None,
            name_from=name_from,
            reply_to=reply_to,
            attachments=file_attachment,
            content_type=content_type,
        )

        logger.info({
            'action': 'email_loan_sphp_request',
            'email': email_to,
            'template': template
        })
        template = 'loan_agreement_email_send'

        return status, headers, subject, msg, template
