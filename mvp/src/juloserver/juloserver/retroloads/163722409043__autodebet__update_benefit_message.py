# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2021-11-18 08:28
from __future__ import unicode_literals

from django.db import migrations

from juloserver.julo.models import FeatureSetting
from juloserver.autodebet.constants import FeatureNameConst


def update_feature_settings_benefit_autodebet_bca(apps, _schema_editor):
    feature_setting = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.BENEFIT_AUTODEBET_BCA
    ).last()
    cashback = {
        "type": "cashback",
        "percentage": 0,
        "amount": 20000,
        "status": "active",
        "message": "Aktifkan sekarang, dapat cashback {}"
    }
    waive_interest = {
        "type": "waive_interest",
        "percentage": 100,
        "amount": 0,
        "status": "active",
        "message": "Aktifkan sekarang, gratis bunga di cicilan pertama Anda."
    }
    feature_setting.update_safely(parameters=[cashback, waive_interest])


class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.RunPython(
            update_feature_settings_benefit_autodebet_bca, migrations.RunPython.noop),
    ]
