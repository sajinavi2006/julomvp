from builtins import str
import logging
from builtins import str
from django.core.management.base import BaseCommand, CommandError
from django.conf import settings
from juloserver.julo.models import Customer
from juloserver.julo.product_lines import ProductLineCodes
from juloserver.moengage.services.use_cases import (
    bulk_create_moengage_upload_customer_update_j1,
    update_moengage_for_user_attribute_j1,
)


class Command(BaseCommand):
    help = 'One time bulk update new attribute next_cashback_expiry_date & next_cashback_expiry_total_amount to existing customer on moengage'

    def handle(self, *args, **options):
        update_data = ['next_cashback_expiry_date', 'next_cashback_expiry_total_amount']
        try:
            moengage_upload_data = Customer.objects.filter(
                application__product_line_id=ProductLineCodes.J1, cashbackbalance__cashback_balance__gt=0
            ).values_list('id', flat=True)
            moengage_upload_batch_id = bulk_create_moengage_upload_customer_update_j1(update_data, moengage_upload_data)
            update_moengage_for_user_attribute_j1.delay(moengage_upload_batch_id, update_data)
        except Exception as e:
            CommandError(str(e))
