# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2024-05-30 04:46
from __future__ import unicode_literals

from django.db import migrations

from juloserver.autodebet.constants import FeatureNameConst
from juloserver.julo.models import FeatureSetting


def create_autodebet_and_whitelist_feature_dana(apps, _schema_editor):
    FeatureSetting.objects.create(
        feature_name=FeatureNameConst.AUTODEBET_DANA,
        parameters={
            "disable": {
                "disable_start_date_time": "12-12-2023 09:00",
                "disable_end_date_time": "12-12-2023 11:00",
            },
        },
        is_active=False,
        category="repayment",
        description="Autodebet DANA",
    )

    FeatureSetting.objects.create(
        feature_name=FeatureNameConst.WHITELIST_AUTODEBET_DANA,
        parameters={"applications": []},
        is_active=False,
        category="repayment",
        description="Whitelist application who can use Autodebet DANA",
    )


class Migration(migrations.Migration):

    dependencies = []

    operations = [
        migrations.RunPython(
            create_autodebet_and_whitelist_feature_dana, migrations.RunPython.noop
        ),
    ]
