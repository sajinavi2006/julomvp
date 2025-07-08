from builtins import str
import logging
import sys

from django.core.management.base import BaseCommand

from juloserver.collection_vendor.models import CollectionVendor

logger = logging.getLogger(__name__)
logger.addHandler(logging.StreamHandler(sys.stdout))


class Command(BaseCommand):
    help = 'retroload collection vendor table'

    def handle(self, *args, **options):
        try:
            vendor_names = ['Selaras', 'Xing Hao', 'Rajawali',
                            'Sakinah Sahabat Senter']
            collection_vendor_data = []
            for vendor_name in vendor_names:
                collection_vendor_data.append(
                    CollectionVendor(
                        vendor_name=vendor_name,
                        is_special=True,
                        is_general=True,
                        is_final=True,
                    )
                )
            CollectionVendor.objects.bulk_create(collection_vendor_data)
        except Exception as e:
            error_msg = 'Something went wrong -{}'.format(str(e))
            logger.error(error_msg)
            self.stdout.write(self.style.ERROR(error_msg))
