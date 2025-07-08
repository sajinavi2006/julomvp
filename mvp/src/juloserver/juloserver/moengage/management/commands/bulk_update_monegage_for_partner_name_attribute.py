from builtins import str
import logging
from builtins import str
from django.core.management.base import BaseCommand, CommandError
from django.conf import settings
from juloserver.moengage.services.use_cases import (bulk_create_moengage_upload_customer_update_j1,
                                                    update_moengage_for_user_attribute_j1)

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'One time bulk update new attribute partner_name to existing customer on moengage'

    def handle(self, *args, **options):
        update_data = ['partner_name']
        try:
            moengage_upload_batch_id = bulk_create_moengage_upload_customer_update_j1(update_data)
            update_moengage_for_user_attribute_j1.delay(moengage_upload_batch_id, update_data)
        except Exception as e:
            CommandError(str(e))
