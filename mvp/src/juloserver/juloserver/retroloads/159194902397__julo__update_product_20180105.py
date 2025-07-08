# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import migrations
from juloserver.julo.product_lines import ProductLineCodes


from juloserver.julo.models import ProductLookup



from juloserver.julo.models import ProductLine



from juloserver.julo.models import ProductLookup



from juloserver.julo.models import ProductLine



def update_product_line_grab(apps, schema_editor):
    
    
    
    product_line_grab1 = ProductLine.objects.get(
        product_line_code=ProductLineCodes.GRAB1)
    product_line_grab2 = ProductLine.objects.get(
        product_line_code=ProductLineCodes.GRAB2)
    product_lookup_grab1 = ProductLookup.objects.get(
        product_line=product_line_grab1)
    product_lookup_grab2 = ProductLookup.objects.get(
        product_line=product_line_grab2)
    product_line_grab1.min_interest_rate = 0
    product_line_grab1.max_interest_rate = 0
    product_line_grab2.min_interest_rate = 0
    product_line_grab2.max_interest_rate = 0
    product_lookup_grab1.interest_rate = 0
    product_lookup_grab2.interest_rate = 0
    product_lookup_grab1.late_fee_pct = 0
    product_lookup_grab2.late_fee_pct = 0
    product_lookup_grab1.origination_fee_pct = 0.05
    product_lookup_grab2.origination_fee_pct = 0.05
    product_lookup_grab1.product_name = "I.000-O.050-L.000-C1.000-C2.000-M"
    product_lookup_grab2.product_name = "I.000-O.050-L.000-C1.000-C2.000-M"
    product_line_grab1.save()
    product_line_grab2.save()
    product_lookup_grab1.save()
    product_lookup_grab2.save()

def update_product_line_bri(apps, schema_editor):
    
    
    
    product_line_bri1 = ProductLine.objects.get(
        product_line_code=ProductLineCodes.BRI1)
    product_line_bri2 = ProductLine.objects.get(
        product_line_code=ProductLineCodes.BRI2)
    product_lookup_bri1 = ProductLookup.objects.get(
        product_line=product_line_bri1)
    product_lookup_bri2 = ProductLookup.objects.get(
        product_line=product_line_bri2)
    product_lookup_bri1.product_name = "I.480-O.000-L.050-C1.000-C2.000-M"
    product_lookup_bri2.product_name = "I.480-O.000-L.050-C1.000-C2.000-M"
    product_lookup_bri1.save()
    product_lookup_bri2.save()

class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.RunPython(update_product_line_grab),
        migrations.RunPython(update_product_line_bri),
    ]
