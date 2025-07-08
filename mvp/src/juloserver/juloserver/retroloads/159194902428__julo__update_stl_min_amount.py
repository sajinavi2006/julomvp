# -*- coding: utf-8 -*-
# manual migration
from __future__ import unicode_literals

from django.db import migrations

from juloserver.julo.models import ProductLine


def update_stl_min_amount(apps, schema_editor):
    for stl in ["STL1", "STL2"]:
        

        product_line = ProductLine.objects.get(product_line_type=stl)
        product_line.min_amount = 500000
        product_line.save()

        product_profile = product_line.product_profile
        product_profile.min_amount = 500000
        product_profile.save()

class Migration(migrations.Migration):
    dependencies = [
    ]

    operations = [
        migrations.RunPython(update_stl_min_amount, migrations.RunPython.noop),
    ]
