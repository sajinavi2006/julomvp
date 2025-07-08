import csv
import logging
import sys

from django.core.management.base import BaseCommand
from django.conf import settings
from datetime import datetime
from juloserver.loan_refinancing.models import CollectionOfferExtensionConfiguration
from django.db import transaction
from pyexcel_xls import get_data

logger = logging.getLogger(__name__)
logger.addHandler(logging.StreamHandler(sys.stdout))


class Command(BaseCommand):
    help = 'Collection offer extension configurations retroload from xls file'

    def handle(self, *args, **options):
        data = get_data(settings.BASE_DIR + '/misc_files/excel/extension_config.xlsx')
        configurations_list = data['Sheet1']
        configurations_entries = []

        with transaction.atomic():
            for idx, config in enumerate(configurations_list):
                if idx == 0:
                    continue
                data_start = datetime.strptime(config[3], "%Y-%m-%d").date()
                data_end = datetime.strptime(config[4], "%Y-%m-%d").date()
                existing = CollectionOfferExtensionConfiguration.objects.filter(
                    product_type=config[0],
                    remaining_payment=config[1],
                    max_extension=config[2],
                    date_start=data_start,
                    date_end=data_end,
                )

                if existing:
                    self.stdout.write(
                        self.style.WARNING(
                            'Product type {}, Remaining payment {}, Max extension {}, '
                            'Date start {}, Date end {} already exists!'.format(
                                config[0], config[1], config[2], data_start, data_end
                            )
                        )
                    )
                    continue
                configurations_entries.append(
                    CollectionOfferExtensionConfiguration(
                        product_type=config[0],
                        remaining_payment=config[1],
                        max_extension=config[2],
                        date_start=data_start,
                        date_end=data_end,
                    )
                )

            CollectionOfferExtensionConfiguration.objects.bulk_create(configurations_entries)

            self.stdout.write(self.style.SUCCESS(
                'Successfully retro {} data to collection offer '
                'extension configuration table'.format(len(configurations_entries)))
            )
