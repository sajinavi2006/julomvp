# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import migrations
from ..product_lines import ProductLineCodes


def update_product_line_axiata(apps, schema_editor):
    ProductLookup = apps.get_model("julo", "ProductLookup")
    product_lookup_axiata = ProductLookup.objects.filter(
        product_line_id__in=ProductLineCodes.axiata())
    product_lookup_axiata.update(late_fee_pct=0.05)


class Migration(migrations.Migration):

    dependencies = [
        ('julo', '0673_change_field_error_to_text'),
    ]

    operations = [
        migrations.RunPython(update_product_line_axiata)
    ]
