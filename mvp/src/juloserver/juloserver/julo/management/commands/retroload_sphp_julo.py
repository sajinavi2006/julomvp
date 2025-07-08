from builtins import str
import logging
from datetime import datetime
import os
import pdfkit
import tempfile

from django.core.management.base import BaseCommand

from juloserver.julo.models import (Application,
                                    Document)
from juloserver.julo.services import get_sphp_template
from juloserver.julo.tasks import upload_document
from juloserver.julo.constants import ApplicationStatusCodes
from juloserver.julo.product_lines import ProductLineCodes

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'retroload sphp julo'

    def handle(self, *args, **options):
        applications = Application.objects.filter(
            application_status=ApplicationStatusCodes.FUND_DISBURSAL_SUCCESSFUL,
            address_kodepos='',
            product_line__in=ProductLineCodes.mtl()
        )
        applications_id = applications.values_list('id', flat=True)
        documents = Document.objects.values_list('document_source', flat=True).filter(
            document_source__in=applications_id,
            document_type='sphp_julo'
        ).distinct('document_source')

        applications = applications.filter(pk__in=documents)

        if applications:
            for application in applications:
                try:
                    body = get_sphp_template(application.id)
                    if not body:
                        logger.error({
                            'action_view': 'retroload_generate_sphp',
                            'data': {'application_id': application.id},
                            'errors': "Template not found."
                        })
                        return
                    now = datetime.now()
                    filename = '{}_{}_{}_{}.pdf'.format(
                        application.fullname,
                        application.application_xid,
                        now.strftime("%Y%m%d"),
                        now.strftime("%H%M%S"))
                    file_path = os.path.join(tempfile.gettempdir(), filename)

                    try:
                        pdfkit.from_string(body, file_path)
                    except Exception as e:
                        logger.error({
                            'action_view': 'retroload_generate_sphp',
                            'data': {'application_id': application.id},
                            'errors': "Failed to create PDF -{}".format(str(e))
                        })
                        return

                    sphp_julo = Document.objects.create(document_source=application.id,
                                                        document_type='sphp_julo',
                                                        filename=filename,
                                                        application_xid=application.application_xid)

                    logger.info({
                        'action_view': 'retroload_generate_sphp',
                        'data': {'application_id': application.id, 'document_id': sphp_julo.id},
                        'message': "success create PDF"
                    })

                    upload_document(sphp_julo.id, file_path)

                except Exception as e:
                    logger.error({
                        'action_view': 'retroload_generate_sphp',
                        'data': {'application_id': application.id},
                        'errors': str(e)
                    })
