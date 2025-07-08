from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone
import re

from juloserver.julo.models import ProductLookup
from juloserver.julo.product_lines import ProductLineCodes


class Command(BaseCommand):
    help = 'create new rows base on current product lookup j1, jturbo, mtl change late fee to 0.09'

    def handle(self, *args, **options):
        self.stdout.write(self.style.SUCCESS('retroload product lookup begin'))

        try:
            with transaction.atomic():
                product_lookups = ProductLookup.objects.filter(
                    product_line_id__in=[
                        ProductLineCodes.J1, ProductLineCodes.JTURBO, ProductLineCodes.MTL1,
                        ProductLineCodes.MTL2
                    ],
                )
                for product_lookup in product_lookups:
                    today = timezone.localtime(timezone.now())
                    product_lookup.cdate = today
                    product_lookup.udate = today
                    product_lookup.pk = None
                    product_lookup.product_name = re.sub(
                        r"L\.\d{3}", "L.009", product_lookup.product_name
                    )
                    product_lookup.late_fee_pct = 0.09
                    product_lookup.save()
        except Exception as e:
            self.stdout.write(self.style.ERROR(str(e)))

        self.stdout.write(self.style.SUCCESS('Success retroload product lookup'))

