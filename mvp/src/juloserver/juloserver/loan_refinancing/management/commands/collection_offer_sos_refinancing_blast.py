import sys
import logging
from django.core.management.base import BaseCommand
from juloserver.loan_refinancing.tasks import blast_email_sos_refinancing

logger = logging.getLogger(__name__)
logger.addHandler(logging.StreamHandler(sys.stdout))


class Command(BaseCommand):

    def add_arguments(self, parser):
        parser.add_argument('-f', '--file', type=str, help='Define file name')

    def handle(self, **options):
        """
        blast email sos refinancing
        """
        try:
            path = options['file']
            self.stdout.write(self.style.WARNING('SOS Refinancing Email Blast'))
            blast_email_sos_refinancing.delay(path)
            self.stdout.write(self.style.WARNING(
                'Sent to Async server'))
        except Exception as e:
            response = 'Failed to blast sos refinancing'
            error_msg = 'Something went wrong -{}'.format(str(e))
            logger.error({
                'status': response,
                'reason': error_msg
            })
            raise e
