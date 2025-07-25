# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2022-04-11 16:08
from __future__ import unicode_literals

from django.db import migrations
from juloserver.julo.models import ProductLine, ProductLookup, ProductProfile
from juloserver.portal.object.product_profile.services import \
    generate_product_lookup


def update_ef_product_line(apps, schema_editor):
    # update product profile
    product_profile = ProductProfile.objects.get(code='500')
    product_profile.late_fee = 0.05
    product_profile.interest_rate_increment = 0.005
    product_profile.save()

    # get existing product line
    product_line = ProductLine.objects.get(product_line_code=500)

    # clear existing product lookup
    ProductLookup.objects.filter(product_line=500).delete()

    # generate new product lookup
    product_lookup_list = generate_product_lookup(product_profile, product_line)
    for product_lookup_data in product_lookup_list:
        product_lookup = ProductLookup(**product_lookup_data)
        product_lookup.save()


class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.RunPython(update_ef_product_line, migrations.RunPython.noop)
    ]
