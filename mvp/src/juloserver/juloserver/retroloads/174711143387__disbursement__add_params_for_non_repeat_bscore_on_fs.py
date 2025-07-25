# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2025-05-13 04:43
from __future__ import unicode_literals

from django.db import migrations
from juloserver.julo.constants import FeatureNameConst
from juloserver.julo.models import FeatureSetting


def update_parameter_on_daily_disbursment_limit_fs(apps, schema_editor):
    fs = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.DAILY_DISBURSEMENT_LIMIT
    ).last()
    if fs:
        new_parameters = fs.parameters or {}
        new_parameters['non_repeat_bscore_amount'] = 0
        fs.update_safely(parameters=new_parameters)


class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.RunPython(
            update_parameter_on_daily_disbursment_limit_fs, migrations.RunPython.noop
        )
    ]
