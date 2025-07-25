# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2021-06-30 05:58
from __future__ import unicode_literals

from django.db import migrations
from juloserver.loan.constants import LoanFeatureNameConst

def create_and_populate_transaction_method_limit_feature_setting(apps, _schema_editor):
    feature_setting = apps.get_model("julo", "FeatureSetting")
    transaction_method = apps.get_model("payment_point", "TransactionMethod")
    method_names = transaction_method.objects.all().values_list('method', flat=True)
    initial_data = {}
    for name in method_names:
        initial_data[name] = {
            '24 hr': 10,
            '1 hr': 5,
            '5 min': 1,
            'is_active': True
            }
    errors = {
        '24 hr': "Maaf Anda telah mencapai batas maksimal transaksi harian. Silakan coba lagi besok",
        'other': "Mohon tunggu sebentar untuk melakukan transaksi ini"
    }
    initial_data['errors'] = errors
    feature = feature_setting.objects.create(
        is_active=False,
        feature_name=LoanFeatureNameConst.TRANSACTION_METHOD_LIMIT,
        parameters=initial_data)


class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.RunPython(create_and_populate_transaction_method_limit_feature_setting, migrations.RunPython.noop)
    ]
