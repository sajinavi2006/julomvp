# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2021-08-08 19:57
from __future__ import unicode_literals
from juloserver.julo.constants import FeatureNameConst

from django.db import migrations


def update_bonza_feature_settings_parameters(apps, schema_editor):
    FeatureSetting = apps.get_model("julo", "FeatureSetting")
    feature = FeatureSetting.objects.get(
        feature_name=FeatureNameConst.BONZA_LOAN_SCORING)
    feature.parameters = {
        'bonza_scoring_threshold': 50}
    feature.save()


class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.RunPython(update_bonza_feature_settings_parameters, migrations.RunPython.noop)
    ]
