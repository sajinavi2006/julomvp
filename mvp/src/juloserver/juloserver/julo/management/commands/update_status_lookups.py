import logging
import sys

from django.core.management.base import BaseCommand

from ...models import StatusLookup
from ...statuses import Statuses
from ...workflows2.schemas.default_status_handler import *
from . import update_status_label


logger = logging.getLogger(__name__)
logger.addHandler(logging.StreamHandler(sys.stdout))


class Command(BaseCommand):
    help = 'Update status lookup table'

    def handle(self, *args, **options):
        status_label_cmd = update_status_label.Command()

        for status in Statuses:

            status_lookup = StatusLookup.objects.filter(
                status_code=status.code).first()

            if status_lookup is not None:
                logger.info({
                    'julo_status_code': status.code,
                    'status': 'already_exists',
                    'action': 'updating_data'
                })
                status_lookup.status = status.desc
                if status.code in STATUSES_WHICH_HAS_HANDLER:
                    status_lookup.handler = 'Status%sHandler' % status.code
                status_lookup.save()
            else:
                logger.debug({
                    'new_julo_status_code': status.code,
                    'description': status.desc,
                    'status': 'already_exists'
                })
                status_lookup = StatusLookup(
                    status_code=status.code, status=status.desc)
                if status.code in STATUSES_WHICH_HAS_HANDLER:
                    status_lookup.handler = 'Status%sHandler' % status.code
                status_lookup.save()
        status_label_cmd.handle()
