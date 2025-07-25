# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2023-06-04 22:48
from __future__ import unicode_literals

from django.db import migrations

from juloserver.julo.constants import FeatureNameConst
from juloserver.julo.models import FeatureSetting


def add_new_parameters_grab_file_transfer_call_feature_setting(apps, _schema_editor):
    feature_setting = FeatureSetting.objects.get_or_none(
        feature_name=FeatureNameConst.GRAB_FILE_TRANSFER_CALL)
    if feature_setting and feature_setting.parameters:
        feature_setting.parameters['loan_per_file'] = 1000
        feature_setting.parameters['transaction_per_file'] = 25000
        feature_setting.save()


class Migration(migrations.Migration):
    dependencies = [
    ]

    operations = [
        migrations.RunPython(add_new_parameters_grab_file_transfer_call_feature_setting,
                             migrations.RunPython.noop),
    ]
