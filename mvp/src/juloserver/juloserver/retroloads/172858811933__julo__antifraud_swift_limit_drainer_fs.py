# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2024-10-10 19:21
from __future__ import unicode_literals

from django.db import migrations
from juloserver.julo.models import FeatureSetting
from juloserver.antifraud.constant.feature_setting import BinaryCheck, Holdout


def create_feature_settings_antifraud_swift_limit_drainer(apps, _schema_editor):
    feature_setting = FeatureSetting.objects.filter(feature_name='abc_swift_limit_drainer')

    if not feature_setting.exists():
        FeatureSetting.objects.create(
            feature_name='abc_swift_limit_drainer',
            is_active=False,
            category="antifraud",
            description="Feature Flag for antifraud binary check swift limit drainer",
            parameters={
                BinaryCheck.Parameter.HOLDOUT: {
                    BinaryCheck.Parameter.Holdout.TYPE: Holdout.Type.INACTIVE,
                    BinaryCheck.Parameter.Holdout.REGEX: "",
                    BinaryCheck.Parameter.Holdout.PERCENTAGE: 100,
                },
            },
        )


class Migration(migrations.Migration):

    dependencies = []

    operations = [
        migrations.RunPython(
            create_feature_settings_antifraud_swift_limit_drainer, migrations.RunPython.noop
        )
    ]
