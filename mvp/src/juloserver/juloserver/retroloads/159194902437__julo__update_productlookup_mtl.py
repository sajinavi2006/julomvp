# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import migrations
from juloserver.julo.product_lines import ProductLineCodes


from juloserver.julo.models import ProductLookup



def update_product_lookup_mtl(apps, schema_editor):
    
    product_lookups = ProductLookup.objects.filter(
        product_line__in=[ProductLineCodes.MTL1,ProductLineCodes.MTL2])
    for product in product_lookups:
        product.cashback_initial_pct = 0
        product.save()

class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.RunPython(update_product_lookup_mtl,
                             migrations.RunPython.noop)
    ]
