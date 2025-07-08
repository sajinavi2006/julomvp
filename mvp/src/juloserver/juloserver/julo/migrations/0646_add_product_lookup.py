from __future__ import unicode_literals

import csv

from django.db import migrations
from django.db import transaction



def update_product_lookup_data(apps, _schema_editor):
    """"""
    ProductLookup = apps.get_model("julo", "ProductLookup")
    all_mtl_product = ProductLookup.objects.filter(origination_fee_pct=0.05, product_line_id__in=[10, 11])

    for product in all_mtl_product:
        new_origination_fee_pct=0.07
        new_product_name = product.product_name.replace('O.050', 'O.070')
        if not ProductLookup.objects.filter(
            product_line_id=product.product_line_id,
            product_name=new_product_name
        ).exists():
            ProductLookup.objects.create(
                product_name=new_product_name,
                interest_rate=product.interest_rate,
                origination_fee_pct=new_origination_fee_pct,
                late_fee_pct=product.late_fee_pct,
                cashback_initial_pct=product.cashback_initial_pct,
                cashback_payment_pct=product.cashback_payment_pct,
                is_active=product.is_active,
                product_line_id=product.product_line_id,
                product_profile_id=product.product_profile_id,
            )


class Migration(migrations.Migration):

    dependencies = [
        ('julo', '0645_add_product_on_credit_matrix'),
    ]

    operations = [
        migrations.RunPython(update_product_lookup_data, migrations.RunPython.noop),
    ]
