import base64
import logging
import os
import tempfile

import pdfkit
from celery import task
from django.template.loader import render_to_string

from juloserver.customer_module.constants import MasterAgreementConst
from juloserver.julo.clients import get_julo_email_client
from juloserver.julo.models import (
    Application,
    Document,
    EmailHistory,
    MasterAgreementTemplate,
)

logger = logging.getLogger(__name__)


@task(queue="application_normal")
def generate_application_master_agreement(application_id, new_signature=False):
    from juloserver.customer_module.services.customer_related import (
        PpfpBorrowerSignature,
        PpfpProviderSignature,
    )

    # from django.contrib.auth.models import User
    from juloserver.julo.models import AuthUser as User

    from juloserver.customer_module.services.digital_signature import DigitalSignature
    from juloserver.julo.tasks import upload_document

    application = Application.objects.get(pk=application_id)

    if (
        not application
        or not application.is_julo_one_product()
        and not application.is_julo_starter()
    ):
        logger.error(
            {
                'action_view': 'Master Agreement - generate_application_master_agreement',
                'data': {},
                'errors': 'Application tidak valid',
            }
        )
        return False

    ma_template = MasterAgreementTemplate.objects.filter(product_name='J1', is_active=True).last()

    if not ma_template:
        logger.error(
            {
                'action_view': 'Master Agreement - generate_application_master_agreement',
                'data': {},
                'errors': 'Master Agreement Template tidak ditemukan',
            }
        )
        return False

    if len(ma_template.parameters) == 0:
        logger.error(
            {
                'action_view': 'Master Agreement - generate_application_master_agreement',
                'data': {},
                'errors': 'Body content tidak ada',
            }
        )
        return False

    from juloserver.customer_module.services.customer_related import (
        master_agreement_pdf,
    )

    code = "PPFP-" + str(application.application_xid)
    ma_content = master_agreement_pdf(application, ma_template.parameters, new_signature).replace(
        "\n", ""
    )

    temp_dir = tempfile.gettempdir()

    filename = 'master_agreement-{}.pdf'.format(code)
    file_path = os.path.join(temp_dir, filename)

    try:
        file = open(file_path, "w+b")
        pdfkit.from_string(ma_content, file_path)
        file.close()
    except Exception:
        logger.error(
            {
                'action_view': 'Master Agreement - generate_application_master_agreement',
                'data': {'application_id': application.id},
                'errors': "Failed to create PDF",
            }
        )
        return False

    # Sign the document
    if new_signature:
        provider = User.objects.filter(username='athe.ginting').last()
    else:
        provider = User.objects.filter(username='adri').last()

    provider_signer = DigitalSignature.Signer(
        user=provider,
        signature=PpfpProviderSignature,
        key_name='key-{}-1'.format(provider.id),
        for_organization=True,
    )
    customer_signer = DigitalSignature.Signer(
        user=application.customer.user,
        signature=PpfpBorrowerSignature,
        key_name='key-{}-1'.format(application.customer.user.id),
        full_name=application.customer.fullname,
        email=application.customer.email,
        province=application.address_provinsi or "",
        city=application.address_kabupaten or "",
        address=application.address_street_num or "",
        postal_code=application.address_kodepos or "",
    )

    doc = DigitalSignature.Document(path=file_path)
    file_path = doc.add_signer(provider_signer).add_signer(customer_signer).sign()
    signature = customer_signer.sign(path=file_path)

    document = Document.objects.create(
        key_id=signature['key_id'],
        document_source=application.id,
        document_type='master_agreement',
        filename=filename,
        hash_digi_sign=signature['signature'],
        accepted_ts=signature['created_at'],
        application_xid=application.application_xid,
        signature_version=signature['version'],
    )
    customer_signer.record_history(
        document,
        action="sign",
        note="Customer successfully generate signature in master agreement.",
    )
    doc.record_history(
        document,
        action="sign",
        note="Customer successfully generate certificate signature in master agreement.",
    )
    # customer_signer.verify(document, signature)

    logger.info(
        {
            'action_view': 'Master Agreement - generate_application_master_agreement',
            'data': {'application_id': application.id, 'document_id': document.id},
            'message': "success create PDF",
        }
    )

    with open(file_path, 'rb') as f:
        data = f.read()
    paa = base64.b64encode(data)
    pdf_agreement_attachment = {
        "content": paa.decode(),
        "filename": document.filename,
        "type": "application/pdf",
    }

    signature_content = (
        bytes(document.hash_digi_sign, 'utf-8')
        if isinstance(document.hash_digi_sign, str)
        else document.hash_digi_sign
    )
    signature_attachment = {
        "content": base64.b64encode(signature_content).decode(),
        "filename": "digital_signature.txt",
        "type": "text/plain",
    }

    upload_document(document.id, file_path)
    send_email_master_agreement(
        application_id,
        document.id,
        attachments=[pdf_agreement_attachment, signature_attachment],
    )


@task(queue='application_high')
def send_email_master_agreement(application_id, document_id, **kwargs):
    application = Application.objects.get(pk=application_id)
    customer = application.customer
    subject = MasterAgreementConst.SUBJECT
    template = MasterAgreementConst.TEMPLATE
    email_from = MasterAgreementConst.EMAIL_FROM
    target_email = customer.email

    context = {
        'footer_url': MasterAgreementConst.FOOTER_URL,
        'full_name': application.fullname_with_title,
        'contact_email': MasterAgreementConst.EMAIL_FROM,
        'phone_1': MasterAgreementConst.PHONE_1,
        'phone_2': MasterAgreementConst.PHONE_2,
        "footer_image": "https://julostatics.oss-ap-southeast-5.aliyuncs.com/common/otp/footer.png",
    }
    # footer image same like otp email
    msg = render_to_string(template, context)
    email_to = target_email
    name_from = MasterAgreementConst.NAME_FROM
    email_client = get_julo_email_client()

    status, body, headers = email_client.send_email(
        subject,
        msg,
        email_to,
        email_from=email_from,
        email_cc=None,
        name_from=name_from,
        reply_to=email_from,
        attachments=kwargs['attachments'],
        content_type="text/html",
    )

    email_history = EmailHistory.objects.create(
        status=status,
        customer=customer,
        sg_message_id=headers['X-Message-Id'],
        to_email=target_email,
        subject=subject,
        message_content=msg,
        template_code='master_agreement_email',
    )

    logger.info(
        "email_master_agreement|customer_id={}, document_id={}, "
        "email_history_id={}".format(customer.id, document_id, email_history.id)
    )
