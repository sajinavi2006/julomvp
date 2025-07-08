import os
import base64
import logging
import pdfkit
from django.conf import settings
from datetime import datetime
from django.db.models import Sum

from juloserver.grab.utils import GrabUtils
from juloserver.julo.models import Loan, EmailHistory, Document, Payment
from juloserver.loan.services.views_related import get_sphp_template_grab
from juloserver.fdc.files import TempDir
from juloserver.julo.clients import get_julo_email_client
from juloserver.julo.tasks import upload_document
from django.template.loader import render_to_string
from juloserver.julo.utils import display_rupiah
from juloserver.julo.statuses import PaymentStatusCodes

logger = logging.getLogger(__name__)
email_client = get_julo_email_client()


def trigger_sending_email_sphp(loan_id):
    with TempDir() as tempdir:
        loan = Loan.objects.get_or_none(pk=loan_id)
        if not loan:
            logger.error({
                'action_view': 'trigger_sending_email_sphp',
                'data': {'loan_id': loan_id},
                'errors': "Loan_id Not found."
            })
        body = get_sphp_template_grab(loan_id, type="email")
        if not body:
            logger.error({
                'action_view': 'trigger_sending_email_sphp',
                'data': {'loan_id': loan_id},
                'errors': "Template tidak ditemukan."
            })
            return
        now = datetime.now()
        last_application = loan.account.application_set.last()
        filename = '{}_{}_{}_{}.pdf'.format(
            last_application.fullname,
            loan.loan_xid,
            now.strftime("%Y%m%d"),
            now.strftime("%H%M%S"))
        file_path = os.path.join(tempdir.path, filename)
        try:
            pdfkit.from_string(body, file_path)
        except Exception as e:
            logger.error({
                'async_action': 'trigger_sending_email_sphp',
                'data': {'loan_id': loan_id},
                'errors': "Failed to create PDF"
            })
            return

        # digital signature
        user = last_application.customer.user
        hash_digi_sign, key_id, accepted_ts = GrabUtils.create_digital_signature(
            user, file_path)

        # create the doc with hash_digi_sign (DigitalSignature)
        sphp_grab = Document.objects.create(document_source=loan.id,
                                            document_type='sphp_grab',
                                            filename=filename,
                                            loan_xid=loan.loan_xid,
                                            hash_digi_sign=hash_digi_sign,
                                            key_id=key_id,
                                            accepted_ts=accepted_ts,
                                            )

        logger.info({
            'action_view': 'trigger_sending_email_sphp',
            'data': {'loan_id': loan_id, 'document_id': sphp_grab.id},
            'message': "success create PDF"
        })

        send_grab_restructure_email(loan, last_application, file_path, filename)
        upload_document(sphp_grab.id, file_path, is_loan=True)


def send_grab_restructure_email(loan, last_application, file_path, filename):
    with open(file_path, 'rb') as f:
        data = f.read()

    subject = "Program Keringanan Cicilan Harian GrabModal powered by JULO"
    template = 'grab_email_template.html'
    email_from = 'cs@julo.co.id'
    target_email = loan.customer.email
    pending_payments = Payment.objects.filter(
        payment_status__status_code__in={
            PaymentStatusCodes.PAYMENT_NOT_DUE,
            PaymentStatusCodes.PAYMENT_DUE_IN_3_DAYS,
            PaymentStatusCodes.PAYMENT_DUE_TODAY,
            PaymentStatusCodes.PAYMENT_DUE_IN_1_DAYS,
            PaymentStatusCodes.PAYMENT_1DPD,
            PaymentStatusCodes.PAYMENT_4DPD,
            PaymentStatusCodes.PAYMENT_5DPD,
            PaymentStatusCodes.PAYMENT_8DPD,
            PaymentStatusCodes.PAYMENT_30DPD,
            PaymentStatusCodes.PAYMENT_60DPD,
            PaymentStatusCodes.PAYMENT_90DPD,
            PaymentStatusCodes.PAYMENT_120DPD,
            PaymentStatusCodes.PAYMENT_150DPD,
            PaymentStatusCodes.PAYMENT_180DPD
    },
        loan=loan
    ).only('id', 'loan_id', 'due_date', 'due_amount')
    total_due_amount = pending_payments.aggregate(Sum('due_amount'))['due_amount__sum']
    total_pending_duration = pending_payments.count()
    context = {
        'image_source': settings.SPHP_STATIC_FILE_PATH + "scraoe-copy-3@3x.png",
        'full_name': last_application.fullname_with_title,
        'installment_amount': display_rupiah(loan.installment_amount),
        'total_outstanding': display_rupiah(total_due_amount),
        'loan_duration': total_pending_duration
    }
    msg = render_to_string(template, context)
    encoded = base64.b64encode(data)
    attachment_dict = {
        "content": encoded.decode(),
        "filename": filename,
        "type": "application/pdf"
    }
    email_to = target_email
    name_from = 'JULO'
    status, body, headers = email_client.send_email(
        subject, msg, email_to, email_from=email_from, email_cc=None, name_from=name_from,
        reply_to=email_from, attachment_dict=attachment_dict, content_type="text/html")

    EmailHistory.objects.create(
        customer=loan.customer,
        sg_message_id=headers['X-Message-Id'],
        to_email=email_to,
        subject=subject,
        message_content=msg,
        template_code=template,
        status=str(status)
    )
