from builtins import str
import logging
from builtins import str
from django.core.management.base import BaseCommand, CommandError
from django.conf import settings
from juloserver.moengage.services.use_cases import (bulk_create_moengage_retargeting_campaign,
update_moengage_for_retargeting_campaign)

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'One time bulk update new attributes to existing customer on moengage'

    def handle(self, *args, **options):
        try:
            moengage_upload_batch_id = bulk_create_moengage_retargeting_campaign()
            update_moengage_for_retargeting_campaign.delay(moengage_upload_batch_id)
        except Exception as e:
            CommandError(str(e))