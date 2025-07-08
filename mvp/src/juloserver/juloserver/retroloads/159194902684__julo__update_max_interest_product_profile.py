# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import migrations
from juloserver.julo.product_lines import ProductLineCodes


from juloserver.julo.models import ProductProfile



def update_product_profile_mtl(apps, schema_editor):
    
    product_profiles = ProductProfile.objects.filter(
        name__in=["MTL1", "MTL2"])
    for product_profile in product_profiles:
        product_profile.max_interest_rate = 0.06
        product_profile.save()

class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.RunPython(update_product_profile_mtl,
                             migrations.RunPython.noop)
    ]
