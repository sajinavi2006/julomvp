# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2022-05-03 17:31
from __future__ import unicode_literals

from django.db import migrations
from juloserver.julo.models import FeatureSetting
from juloserver.julo.constants import FeatureNameConst

def change_parameters(apps, schema_editor):
    credit_limit_feature_setting = FeatureSetting.objects.get_or_none(
        is_active=True,
        feature_name=FeatureNameConst.CREDIT_LIMIT_REJECT_AFFORDABILITY,
    )
    credit_limit_feature_setting.update_safely(parameters={
                                                            "limit_value_sf": 900000,
                                                            "limit_value_lf": 300000
                                                         },
                                                is_active=False
                                               )


class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.RunPython(change_parameters)
    ]
