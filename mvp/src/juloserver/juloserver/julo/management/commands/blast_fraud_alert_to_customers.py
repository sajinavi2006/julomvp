import logging
import sys

from django.core.management.base import BaseCommand
from ...tasks import email_fraud_alert_blast

logger = logging.getLogger(__name__)
logger.addHandler(logging.StreamHandler(sys.stdout))


class Command(BaseCommand):
    help = 'Blast fraud alert (fake julo pinance FB page ) to all customers '

    def handle(self, *args, **options):
        email_fraud_alert_blast.delay()
        self.stdout.write(self.style.SUCCESS("blast email triggered on background"))
        self.stdout.write(self.style.WARNING("see celery log for inspect"))
