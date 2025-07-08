import logging
from celery import task
from juloserver.julo.models import Document, Loan
from juloserver.loan.services.notification import LoanEmail
from juloserver.julo.clients import get_julo_sentry_client, get_julo_email_client
from juloserver.julo.models import EmailHistory
from juloserver.julo.constants import EmailDeliveryAddress


logger = logging.getLogger(__name__)
julo_sentry_client = get_julo_sentry_client()


@task(queue="loan_high")
def upload_sphp_to_oss(loan_id):
    from juloserver.followthemoney.tasks import (
        generate_julo_one_loan_agreement, regenerate_sphp_loan)
    from juloserver.promo.services import get_interest_discount_promo_code_benifit_applied

    loan = Loan.objects.get(id=loan_id)
    logger.info({
        "task": "upload_sphp_to_oss",
        "loan_id": loan.id
    })
    document = Document.objects.filter(
        document_source=loan.id,
        loan_xid=loan.loan_xid,
        document_type__in=("sphp_julo", "sphp_digisign", "sphp_privy")
    ).last()

    if not document:
        generate_julo_one_loan_agreement.apply_async((loan.id,), countdown=5)
    else:
        # for interest discount promo, re-upload sphp
        if get_interest_discount_promo_code_benifit_applied(loan):
            regenerate_sphp_loan.delay(loan.id)


@task(queue='loan_normal')
def send_sphp_email_task(loan_id, retry=0):
    loan = Loan.objects.get_or_none(pk=loan_id)
    try:
        LoanEmail(loan).send_sphp_email()
    except Exception as e:
        retry += 1
        logger.info({
            'task': 'send_sphp_email_task',
            'loan_id': loan_id,
            'retry_times': retry,
            'error': str(e),
        })
        if retry < 3:
            send_sphp_email_task.apply_async((loan_id, retry,), countdown=60)
        else:
            julo_sentry_client.captureException()


@task(queue='send_event_for_skrtp_regeneration_queue')
def send_email_for_skrtp_regeneration(loan_id, retry=0):
    """
        We can't use send_sphp_email_task function because
            we use another template
    """
    from juloserver.loan.services.sphp import (
        get_update_skrtp_email_template,
        get_pdf_file_attachment,
    )
    loan = Loan.objects.get_or_none(pk=loan_id)
    application = loan.account.application_set.last()
    customer = loan.customer
    email_to = customer.email

    subject = "Yuk, cek pembaruan di Surat Konfirmasi Rincian Transaksi Pendanaanmu!"

    try:
        email_client = get_julo_email_client()
        # Get the latest SKRTP document
        document = Document.objects.filter(
            document_source=loan_id,
            document_type="skrtp_julo",
        ).last()
        template = get_update_skrtp_email_template(application)
        pdf_attachment = get_pdf_file_attachment(document)
        _, _, headers = email_client.send_email(
            subject,
            template,
            email_to,
            attachments=[pdf_attachment],
            email_from=EmailDeliveryAddress.CS_JULO,
            name_from='JULO',
            content_type="text/html",
        )
        logger.info(
            {
                'action': 'send_email_for_skrtp_regeneration',
                'email': email_to,
            }
        )
        EmailHistory.objects.create(
            customer=customer,
            sg_message_id=headers["X-Message-Id"],
            to_email=email_to,
            subject=subject,
            application=application,
            message_content=template,
            template_code="regenerate_SKRTP",
        )
    except Exception as e:
        retry += 1
        logger.info({
            'task': 'send_email_for_skrtp_regeneration',
            'loan_id': loan_id,
            'retry_times': retry,
            'error': str(e),
        })
        if retry < 3:
            send_email_for_skrtp_regeneration.apply_async((loan_id, retry,), countdown=60)
        else:
            julo_sentry_client.captureException()
