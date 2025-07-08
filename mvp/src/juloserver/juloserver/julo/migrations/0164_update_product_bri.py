# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import migrations
from ..product_lines import ProductLineCodes


def update_product_line(apps, schema_editor):
    
    ProductLine = apps.get_model("julo", "ProductLine")
    ProductLookup = apps.get_model("julo", "ProductLookup")
    product_line_bri1 = ProductLine.objects.get(
        product_line_code=ProductLineCodes.BRI1)
    product_line_bri2 = ProductLine.objects.get(
        product_line_code=ProductLineCodes.BRI2)
    product_lookup_bri1 = ProductLookup.objects.get(
        product_line=product_line_bri1)
    product_lookup_bri2 = ProductLookup.objects.get(
        product_line=product_line_bri2)
    product_line_bri1.min_interest_rate = 0.04
    product_line_bri1.max_interest_rate = 0.04
    product_line_bri2.min_interest_rate = 0.04
    product_line_bri2.max_interest_rate = 0.04
    product_lookup_bri1.interest_rate = 0.48
    product_lookup_bri2.interest_rate = 0.48
    product_line_bri1.save()
    product_line_bri2.save()
    product_lookup_bri1.save()
    product_lookup_bri2.save()
    

class Migration(migrations.Migration):

    dependencies = [
        ('julo', '0163_productline_bri'),
    ]

    operations = [
        migrations.RunPython(update_product_line),
    ]
