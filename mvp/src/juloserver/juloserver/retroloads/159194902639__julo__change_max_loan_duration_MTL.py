# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import migrations

from juloserver.julo.product_lines import ProductLineCodes


from juloserver.julo.models import ProductLine



def update_product_line_for_mtl(apps, _schema_editor):
    
    ProductLine.objects.filter(
        product_line_code__in=ProductLineCodes.mtl()
    ).update(
        min_amount=1000000,
        min_duration=2,
        max_interest_rate=0.07
    )



class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.RunPython(update_product_line_for_mtl, migrations.RunPython.noop)
    ]
