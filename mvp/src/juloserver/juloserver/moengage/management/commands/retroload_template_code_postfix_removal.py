from builtins import str
import logging
from builtins import str
from django.core.management.base import BaseCommand, CommandError
from django.conf import settings
from juloserver.moengage.tasks import (retroload_template_postfix_data)

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Retroload existing data for moengage campaign template code which has @'

    def handle(self, *args, **options):
        try:
            retroload_template_postfix_data.delay()
        except Exception as e:
            CommandError(str(e))