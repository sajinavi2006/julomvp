# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import migrations
from django.utils import timezone
from ..product_lines import ProductLineCodes


def load_product_lookups(apps, schema_editor):
    
    ProductLine = apps.get_model("julo", "ProductLine")
    product_line_bri1 = ProductLine.objects.get(
        product_line_code=ProductLineCodes.BRI1)
    product_line_bri2 = ProductLine.objects.get(
        product_line_code=ProductLineCodes.BRI2)
        
    product_lookups = [
        (25, 'I.060-O.000-L.050-C1.000-C2.000-M', 0.060, 0.000, 0.050, 0.000, 0.000, True, product_line_bri1),
        (26, 'I.060-O.000-L.050-C1.000-C2.000-M', 0.060, 0.000, 0.050, 0.000, 0.000, True, product_line_bri2),
    ]

    ProductLookup = apps.get_model("julo", "ProductLookup")
    for pl in product_lookups:
        kwargs = {
            'product_code': pl[0],
            'product_name': pl[1],
            'interest_rate': pl[2],
            'origination_fee_pct': pl[3],
            'late_fee_pct': pl[4],
            'cashback_initial_pct': pl[5],
            'cashback_payment_pct': pl[6],
            'is_active': pl[7],
            'product_line': pl[8],
            'cdate': timezone.localtime(timezone.now()),
            'udate': timezone.localtime(timezone.now())
        }
        product_lookup = ProductLookup(**kwargs)
        product_lookup.save()


class Migration(migrations.Migration):

    dependencies = [
        ('julo', '0161_auto_20171207_1617'),
    ]

    operations = [
        migrations.RunPython(load_product_lookups),
    ]
