# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2021-06-30 05:58
from __future__ import unicode_literals

from django.db import migrations
from juloserver.loan.constants import LoanFeatureNameConst

def populate_transaction_method_limits_for_new_devices(apps, _schema_editor):
    feature_setting = apps.get_model("julo", "FeatureSetting")
    feature = feature_setting.objects.get(
        feature_name=LoanFeatureNameConst.TRANSACTION_METHOD_LIMIT)
    initial_data = feature.parameters
    method_names = ['e-commerce', 'dompet digital', 'pulsa & paket data']
    new_device_data = {}
    for name in method_names:
        new_device_data[name] = {
            '24 hr': 3,
            '3 hr': 1,
            '1 hr': 1,
            'is_active': True
            }
    initial_data['new_devices'] = new_device_data
    feature.parameters = initial_data
    feature.save()


class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.RunPython(populate_transaction_method_limits_for_new_devices, migrations.RunPython.noop)
    ]
