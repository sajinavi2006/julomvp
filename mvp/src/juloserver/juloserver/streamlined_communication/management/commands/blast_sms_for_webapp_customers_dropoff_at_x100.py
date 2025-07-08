import logging
import sys

from django.core.management.base import BaseCommand
from django.utils import timezone
from datetime import timedelta

from juloserver.julo.models import Application, SmsHistory
from juloserver.julo.statuses import ApplicationStatusCodes
from juloserver.julo.product_lines import ProductLineCodes
from juloserver.streamlined_communication.tasks import send_sms_for_webapp_dropoff_customers_x100

logger = logging.getLogger(__name__)
logger.addHandler(logging.StreamHandler(sys.stdout))

class Command(BaseCommand):
    def handle(self, **options):
        """
        Command to blast sms to existing web app customers who dropoff at x100 without filling the long form.
        """
        try:
            application_ids = Application.objects.filter(
                application_status_id=ApplicationStatusCodes.FORM_CREATED,
                partner__isnull=False,
                web_version__isnull=False,
                product_line_id=ProductLineCodes.J1).values_list('id', flat=True)
            to_exclude = SmsHistory.objects.filter(
                template_code='j1_webapp_sms_x100_dropoff',
                application_id__in=application_ids).values_list('application_id', flat=True)
            application_ids = application_ids.exclude(id__in=to_exclude)
            for application_id in application_ids:
                send_sms_for_webapp_dropoff_customers_x100.delay(application_id, True)
        except Exception as e:
            logger.error({
                'command': 'blast_sms_for_webapp_customers_dropoff_at_x100',
                'error': str(e)})
