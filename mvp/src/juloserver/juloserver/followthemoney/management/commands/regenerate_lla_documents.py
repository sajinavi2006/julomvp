from builtins import str
import logging
import sys
import os
import tempfile

from xhtml2pdf import pisa
from django.core.management.base import BaseCommand
from juloserver.julo.models import (Document,
                                    Application,)
from juloserver.julo.tasks import upload_document
from juloserver.followthemoney.services import get_loan_agreement_template

logger = logging.getLogger(__name__)
logger.addHandler(logging.StreamHandler(sys.stdout))

class Command(BaseCommand):
    def handle(self, **options):
        try:
            documents = Document.objects.filter(document_type='lender_sphp')
            for document in documents:
                application = Application.objects.get_or_none(application_xid=document.application_xid)
                if not application:
                    logger.error({
                        'action_view': 'generate_lender_loan_agreement',
                        'data': {'application_id': application.id},
                        'errors': "Application tidak ditemukan."
                    })
                    return

                lender = application.loan.lender
                body = get_loan_agreement_template(application, lender)

                filename = 'perjanjian_pinjaman-{}.pdf'.format(
                    application.application_xid
                )
                file_path = os.path.join(tempfile.gettempdir(), filename )

                file = open(file_path, "w+b")
                pdf = pisa.CreatePDF(body, dest=file, encoding="UTF-8")
                file.close()

                if pdf.err:
                    logger.error({
                        'action_view': 'generate_lender_loan_agreement',
                        'data': {'application_id': application.id},
                        'errors': "Failed to create PDF"
                    })
                    return

                logger.info({
                    'action_view': 'generate_lender_loan_agreement',
                    'data': {'application_id': application.id, 'document_id': document.id},
                    'message': "success create PDF"
                })

                upload_document.delay(document.id, file_path)

        except Exception as e:
            logger.error({
                'action_view': 'FollowTheMoney - generate_lender_loan_agreement',
                'data': {'application_id': application.id},
                'errors': str(e)
            })