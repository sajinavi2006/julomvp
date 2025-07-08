import sys
import logging
from datetime import timedelta
from django.utils import timezone
from django.core.management.base import BaseCommand
from juloserver.loan_refinancing.tasks import activation_sos_refinancing

logger = logging.getLogger(__name__)
logger.addHandler(logging.StreamHandler(sys.stdout))


class Command(BaseCommand):

    def add_arguments(self, parser):
        parser.add_argument('-d1', '--file', type=str, help='Define file name')
        parser.add_argument('-d2', '--countdown_hours', type=str, help='Define countdown hours')
        parser.add_argument('-d3', '--countdown_minutes', type=str, help='Define sountdown minutes')

    def handle(self, **options):
        """
        activation SOS refinancing
        """
        try:
            path = options['file']
            countdown_hours = int(options['countdown_hours']) if \
                options['countdown_hours'] else 0
            countdown_minutes = int(options['countdown_minutes']) if \
                options['countdown_minutes'] else 0
            now = timezone.localtime(timezone.now())
            self.stdout.write(self.style.WARNING('SOS Refinancing Activation'))
            time_to_activation = now + timedelta(hours=countdown_hours, 
                                                 minutes=countdown_minutes)
            activation_sos_refinancing.apply_async(
                (path,), eta=time_to_activation)
            self.stdout.write(self.style.WARNING(
                'Sent to Async server, will run at {}'.format(time_to_activation)))
        except Exception as e:
            response = 'Failed to activate sos refinancing'
            error_msg = 'Something went wrong -{}'.format(str(e))
            logger.error({
                'status': response,
                'reason': error_msg
            })
            raise e
