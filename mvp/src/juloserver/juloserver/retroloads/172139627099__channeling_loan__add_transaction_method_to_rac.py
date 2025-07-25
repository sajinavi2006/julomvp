# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2024-07-19 13:37
from __future__ import unicode_literals

from django.db import migrations
from juloserver.julo.models import FeatureSetting
from juloserver.channeling_loan.constants import (
    FeatureNameConst,
    ChannelingConst,
    TransactionMethodConst,
)


def update_transaction_method_risk_acceptance_criteria(apps, _schema_editor):
    feature_setting = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.CHANNELING_LOAN_CONFIG
    ).last()
    if not feature_setting:
        return

    for key in feature_setting.parameters.keys():
        feature_setting.parameters[key]['rac'][
            'TRANSACTION_METHOD'
        ] = TransactionMethodConst.TRANSACTION_METHOD_CODES
    feature_setting.save()


class Migration(migrations.Migration):

    dependencies = []

    operations = [
        migrations.RunPython(
            update_transaction_method_risk_acceptance_criteria, migrations.RunPython.noop
        ),
    ]
