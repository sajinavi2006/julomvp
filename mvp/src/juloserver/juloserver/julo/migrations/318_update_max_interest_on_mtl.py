# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import migrations
from ..product_lines import ProductLineCodes


def update_product_line_mtl(apps, schema_editor):
    ProductLine = apps.get_model("julo", "ProductLine")
    product_lines = ProductLine.objects.filter(
        product_line_type__in=["MTL1", "MTL2"])
    for product_line in product_lines:
        product_line.max_interest_rate = 0.06
        product_line.save()

class Migration(migrations.Migration):

    dependencies = [
        ('julo', '0318_fix_va_permata'),
    ]

    operations = [
        migrations.RunPython(update_product_line_mtl,
                             migrations.RunPython.noop)
    ]
