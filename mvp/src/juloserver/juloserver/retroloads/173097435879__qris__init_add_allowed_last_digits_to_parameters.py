# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2024-11-07 10:12
from __future__ import unicode_literals

from django.db import migrations
from juloserver.loan.constants import LoanFeatureNameConst
from juloserver.julo.models import FeatureSetting


def update_qris_eligible_user_parameters(apps, _schema_editor):
    feature_setting = FeatureSetting.objects.filter(
        feature_name=LoanFeatureNameConst.QRIS_WHITELIST_ELIGIBLE_USER
    ).last()

    if feature_setting:
        parameters = feature_setting.parameters or {}
        parameters['allowed_last_digits'] = [1, 3, 5, 7, 9]
        feature_setting.parameters = parameters
        feature_setting.save()


class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.RunPython(update_qris_eligible_user_parameters, migrations.RunPython.noop)
    ]
