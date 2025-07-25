# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2023-11-21 03:51
from __future__ import unicode_literals

from django.db import migrations
from django.utils import timezone

from juloserver.julo.models import FeatureSetting
from juloserver.julo.constants import FeatureNameConst


def add_feature_setting_autodebet_deduction_day(apps, schema_editor):
    FeatureSetting.objects.create(
        feature_name=FeatureNameConst.AUTODEBET_DEDUCTION_DAY,
        parameters={
            "BCA": {
                "deduction_day_type": "payday",
                "last_update": '2000-01-01'
            },
            "BRI": {
                "deduction_day_type": "payday",
                "last_update": '2000-01-01'
            },
            "GOPAY": {
                "deduction_day_type": "payday",
                "last_update": '2000-01-01'
            },
            "MANDIRI": {
                "deduction_day_type": "payday",
                "last_update": '2000-01-01'
            }
        },
        is_active=False,
    )


class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.RunPython(add_feature_setting_autodebet_deduction_day, migrations.RunPython.noop)
    ]
