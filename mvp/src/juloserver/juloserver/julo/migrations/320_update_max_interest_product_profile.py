# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import migrations
from ..product_lines import ProductLineCodes


def update_product_profile_mtl(apps, schema_editor):
    ProductProfile = apps.get_model("julo", "ProductProfile")
    product_profiles = ProductProfile.objects.filter(
        name__in=["MTL1", "MTL2"])
    for product_profile in product_profiles:
        product_profile.max_interest_rate = 0.06
        product_profile.save()

class Migration(migrations.Migration):

    dependencies = [
        ('julo', '319_add_new_mtl_product_lookups'),
    ]

    operations = [
        migrations.RunPython(update_product_profile_mtl,
                             migrations.RunPython.noop)
    ]
