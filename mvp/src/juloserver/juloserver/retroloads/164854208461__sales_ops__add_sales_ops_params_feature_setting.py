# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2022-03-29 08:21
from __future__ import unicode_literals

from django.db import migrations

from juloserver.julo.constants import FeatureNameConst
from juloserver.julo.models import FeatureSetting


def add_more_sales_ops_params(apps, schema_editor):
    feature_setting = FeatureSetting.objects.get(
        feature_name=FeatureNameConst.SALES_OPS,
    )
    parameters = feature_setting.parameters
    parameters['lineup_min_available_days'] = 30
    feature_setting.parameters = parameters
    feature_setting.save()


class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.RunPython(add_more_sales_ops_params, migrations.RunPython.noop),
    ]
