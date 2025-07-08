import csv
import logging
import sys

from django.core.management.base import BaseCommand

from juloserver.julo.models import (ProductProfile, ProductLookup, ProductLine)
from juloserver.julo.product_lines import ProductLineCodes

logger = logging.getLogger(__name__)
logger.addHandler(logging.StreamHandler(sys.stdout))


class Command(BaseCommand):
    help = 'load Product Lookup for julo one'

    def handle(self, *args, **options):
        csv_file_name = 'misc_files/csv/J1_Product_Structure_Product_Lookup.csv'
        try:
            with open(csv_file_name, 'r') as csvfile:
                csv_rows = csv.DictReader(csvfile, delimiter=',')
                rows = [r for r in csv_rows]
            product_profile = ProductProfile.objects.filter(
                name='J1', code=ProductLineCodes.J1
            ).last()
            product_line = ProductLine.objects.filter(
                product_line_code=ProductLineCodes.J1
            ).last()

            for row in rows:
                product_name = row['PRODUCT_NAME']
                interest_rate = float(row['INTEREST_RATE'].replace(',', '.'))
                origination_fee_pct = float(row['ORIGINATION_FEE_PCT'].replace(',', '.'))
                late_fee_pct = float(row['LATE_FEE_PCT'].replace(',', '.'))
                cashback_initial_pct = float(row['CASHBACK_INITIAL_PCT'].replace(',', '.'))
                cashback_payment_pct = float(row['CASHBACK_PAYMENT_PCT'].replace(',', '.'))
                eligible_amount = None
                eligible_duration = None
                admin_fee = None
                ProductLookup.objects.create(
                    product_name=product_name,
                    interest_rate=interest_rate,
                    origination_fee_pct=origination_fee_pct,
                    late_fee_pct=late_fee_pct,
                    cashback_initial_pct=cashback_initial_pct,
                    cashback_payment_pct=cashback_payment_pct,
                    product_line=product_line,
                    product_profile=product_profile,
                    eligible_amount=eligible_amount,
                    eligible_duration=eligible_duration,
                    admin_fee=admin_fee,
                )
                self.stdout.write(self.style.SUCCESS(
                    'Successfully retro product lookup name {}'.format(product_name))
                )

            self.stdout.write(self.style.SUCCESS(
                'Successfully retro product lookup')
            )
        except IOError:
            logger.error("could not open given file " + csv_file_name)
            return
