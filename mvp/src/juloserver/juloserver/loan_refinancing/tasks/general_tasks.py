import logging
import os
import tempfile

from xhtml2pdf import pisa
from celery import task
from juloserver.julo.models import (
    Loan,
    Document
)

logger = logging.getLogger(__name__)


@task(queue="collection_low")
def upload_addendum_pdf_to_oss(loan_id):
    from ..services.loan_related import get_addendum_template
    from juloserver.julo.tasks import upload_document

    loan = Loan.objects.get_or_none(pk=loan_id)
    application = loan.application
    filename = 'addendum-loan-refinancing-{}.pdf'.format(
        application.application_xid
    )
    file_path = os.path.join(tempfile.gettempdir(), filename)
    body = get_addendum_template(application)

    with open(file_path, "wb") as file:
        pdf = pisa.CreatePDF(body, dest=file, encoding="UTF-8")

    if pdf.err:
        logger.error({
            'action_view': 'generate_addendum_pdf',
            'data': {'application_id': application.id},
            'errors': "Failed to create PDF"
        })

        return

    addendum_document = Document.objects.create(
        document_source=application.id,
        document_type='loan_refinancing_addendum',
        filename=filename,
        application_xid=application.application_xid)

    logger.info({
        'action_view': 'upload_addendum_pdf_to_oss',
        'data': {'application_id': application.id, 'document_id': addendum_document.id},
        'message': "success create PDF"
    })

    upload_document.delay(addendum_document.id, file_path)
