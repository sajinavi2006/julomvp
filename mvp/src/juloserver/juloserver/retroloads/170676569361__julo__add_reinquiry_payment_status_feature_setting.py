# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2024-02-01 05:34
from __future__ import unicode_literals

from django.db import migrations
from juloserver.account_payment.constants import FeatureNameConst
from juloserver.julo.models import FeatureSetting


def add_reinquiry_payment_status_feature_setting(apps, _schema_editor):
    data_to_be_created = {
        'feature_name': FeatureNameConst.REINQUIRY_PAYMENT_STATUS,
        'is_active': True,
        'parameters': {
            "interval_minute": 120
        },
        'category': 'repayment',
        'description': 'Setting for adjusting interval in minutes for reinquiry payment status'
    }
    FeatureSetting.objects.get_or_create(**data_to_be_created)


class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.RunPython(add_reinquiry_payment_status_feature_setting, migrations.RunPython.noop),
    ]
