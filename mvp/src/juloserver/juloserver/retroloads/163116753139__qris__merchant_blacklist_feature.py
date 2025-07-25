# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2021-08-08 19:57
from __future__ import unicode_literals
from juloserver.julo.constants import FeatureNameConst

from django.db import migrations


def create_qris_merchant_blacklist_feature(apps, schema_editor):
    FeatureSetting = apps.get_model("julo", "FeatureSetting")
    feature = FeatureSetting.objects.create(
        feature_name=FeatureNameConst.QRIS_MERCHANT_BLACKLIST,
        is_active=True, category='qris',
        description='To prevent suspicious transaction on QRIS')
    feature.parameters = {
        "merchant_category_codes": [],
        "merchant_cities": [],
        "merchant_names": []}
    feature.save()


class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.RunPython(create_qris_merchant_blacklist_feature, migrations.RunPython.noop)
    ]
