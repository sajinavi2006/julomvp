from builtins import str
import logging
import sys

from django.core.management.base import BaseCommand

from juloserver.julo.models import HighScoreFullBypass

logger = logging.getLogger(__name__)
logger.addHandler(logging.StreamHandler(sys.stdout))


class Command(BaseCommand):
    help = 'retroload high score full bypass same configuration with an older version'

    def add_arguments(self, parser):
        parser.add_argument('-o',
                            '--old_version',
                            type=str,
                            required=True,
                            help='Define old version')
        parser.add_argument('-n',
                            '--new_version',
                            type=str,
                            required=True,
                            help='Define new version')

    def handle(self, *args, **options):
        try:
            old_version = options['old_version']
            new_version = options['new_version']
            hsfb_configurations = HighScoreFullBypass.objects.values(
                'threshold', 'is_premium_area', 'is_salaried', 'customer_category', 'cm_version'
            ).filter(cm_version=old_version)
            if hsfb_configurations:
                hsfb_configurations_data = []
                for hsfb_configuration in hsfb_configurations:
                    hsfb_configuration["cm_version"] = new_version
                    hsfb_configurations_data.append(HighScoreFullBypass(**hsfb_configuration))

                HighScoreFullBypass.objects.bulk_create(hsfb_configurations_data)

                self.stdout.write(self.style.SUCCESS('Retroload high score full bypass success'))
        except Exception as e:
            error_msg = 'Something went wrong -{}'.format(str(e))
            logger.error(error_msg)
            self.stdout.write(self.style.ERROR(error_msg))
