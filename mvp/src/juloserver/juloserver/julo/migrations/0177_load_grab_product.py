# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import migrations
from django.utils import timezone
from ..product_lines import ProductLineCodes


def load_product_lookups(apps, schema_editor):

    ProductLine = apps.get_model("julo", "ProductLine")
    product_line_grab1 = ProductLine.objects.get(
        product_line_code=ProductLineCodes.GRAB1)

    pl = [29, 'I.000-O.100-L.000-C1.000-C2.000-M', 0.00, 0.000, 0.100, 0.000, 0.000, True, product_line_grab1]

    ProductLookup = apps.get_model("julo", "ProductLookup")
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
        ('julo', '0176_auto_20180111_1023'),
    ]

    operations = [
        migrations.RunPython(load_product_lookups, migrations.RunPython.noop)
    ]
