# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import migrations
from ..product_lines import ProductLineCodes


def update_product_line_grab(apps, schema_editor):
    
    ProductLine = apps.get_model("julo", "ProductLine")
    ProductLookup = apps.get_model("julo", "ProductLookup")
    product_line_grab1 = ProductLine.objects.get(
        product_line_code=ProductLineCodes.GRAB1)
    product_line_grab2 = ProductLine.objects.get(
        product_line_code=ProductLineCodes.GRAB2)
    product_lookup_grab1 = ProductLookup.objects.get(
        product_line=product_line_grab1)
    product_lookup_grab2 = ProductLookup.objects.get(
        product_line=product_line_grab2)
    product_lookup_grab1.origination_fee_pct = 0.06
    product_lookup_grab2.origination_fee_pct = 0.06
    product_lookup_grab1.product_name = "I.000-O.060-L.000-C1.000-C2.000-M"
    product_lookup_grab2.product_name = "I.000-O.060-L.000-C1.000-C2.000-M"
    product_lookup_grab1.save()
    product_lookup_grab2.save()


class Migration(migrations.Migration):

    dependencies = [
        ('julo', '0174_update_product_20180105'),
    ]

    operations = [
        migrations.RunPython(update_product_line_grab),
    ]
