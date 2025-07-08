# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import migrations
from juloserver.julo.product_lines import ProductLineCodes


from juloserver.julo.models import ProductLine



def update_product_line(apps, schema_editor):
    
    
    product_line_bri1 = ProductLine.objects.get(
        product_line_code=ProductLineCodes.BRI1)
    product_line_bri2 = ProductLine.objects.get(
        product_line_code=ProductLineCodes.BRI2)
    product_line_bri1.min_interest_rate = 0.06
    product_line_bri1.max_interest_rate = 0.06
    product_line_bri2.min_interest_rate = 0.06
    product_line_bri2.max_interest_rate = 0.06
    product_line_bri1.save()
    product_line_bri2.save()
    

class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.RunPython(update_product_line),
    ]
