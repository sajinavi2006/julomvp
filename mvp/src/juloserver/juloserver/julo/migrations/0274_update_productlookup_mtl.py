# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import migrations
from ..product_lines import ProductLineCodes


def update_product_lookup_mtl(apps, schema_editor):
    ProductLookup = apps.get_model("julo", "ProductLookup")
    product_lookups = ProductLookup.objects.filter(
        product_line__in=[ProductLineCodes.MTL1,ProductLineCodes.MTL2])
    for product in product_lookups:
        product.cashback_initial_pct = 0
        product.save()

class Migration(migrations.Migration):

    dependencies = [
        ('julo', '0273_auto_20180814_1032'),
    ]

    operations = [
        migrations.RunPython(update_product_lookup_mtl,
                             migrations.RunPython.noop)
    ]
