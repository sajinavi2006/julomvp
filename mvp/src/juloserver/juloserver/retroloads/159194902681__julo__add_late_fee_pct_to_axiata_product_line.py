# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import migrations
from juloserver.julo.product_lines import ProductLineCodes


from juloserver.julo.models import ProductLookup



def update_product_line_axiata(apps, schema_editor):
    
    product_lookup_axiata = ProductLookup.objects.filter(
        product_line_id__in=ProductLineCodes.axiata())
    product_lookup_axiata.update(late_fee_pct=0.05)


class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.RunPython(update_product_line_axiata)
    ]
