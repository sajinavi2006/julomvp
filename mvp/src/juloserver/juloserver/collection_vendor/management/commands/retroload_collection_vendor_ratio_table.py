from builtins import str
import logging
import sys

from django.core.management.base import BaseCommand

from juloserver.collection_vendor.models import CollectionVendorRatio, CollectionVendor
from juloserver.collection_vendor.constant import CollectionVendorCodes

logger = logging.getLogger(__name__)
logger.addHandler(logging.StreamHandler(sys.stdout))


class Command(BaseCommand):
    help = 'retroload collection vendor ratios table. make sure retroload '\
           'collection vendor table run first before this'

    def handle(self, *args, **options):
        try:
            vendor_names = ['Selaras', 'Xing Hao', 'Rajawali',
                            'Sakinah Sahabat Senter']
            vendor_ratios = {'Selaras': 0.25, 'Xing': 0.25, 'Rajawali': 0.25, 'Sakinah': 0.25}

            vendors = CollectionVendor.objects.filter(
                vendor_name__in=vendor_names,
                is_deleted=False,
            )
            collection_vendor_ratio_data = []
            for vendor_type in CollectionVendorCodes.VENDOR_TYPES:
                for vendor in vendors:
                    collection_vendor_ratio_data.append(CollectionVendorRatio(
                        collection_vendor=vendor,
                        vendor_types=CollectionVendorCodes.VENDOR_TYPES.get(vendor_type),
                        account_distribution_ratio=vendor_ratios[vendor.vendor_name.split(' ')[0]]
                    ))
            CollectionVendorRatio.objects.bulk_create(collection_vendor_ratio_data)
        except Exception as e:
            error_msg = 'Something went wrong -{}'.format(str(e))
            logger.error(error_msg)
            self.stdout.write(self.style.ERROR(error_msg))
