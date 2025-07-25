# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2024-08-16 06:44
from __future__ import unicode_literals

from django.db import migrations

from juloserver.antifraud.constant.feature_setting import BinaryCheck, Holdout
from juloserver.julo.models import FeatureSetting


def create_abc_bank_name_velocity_fs(apps, _schema_editor):
    FeatureSetting.objects.get_or_create(
        feature_name='abc_bank_name_velocity',
        category="antifraud",
        description="Feature Flag for antifraud binary check bank name velocity",
        is_active=False,
        parameters={
            BinaryCheck.Parameter.HOLDOUT: {
                BinaryCheck.Parameter.Holdout.TYPE: Holdout.Type.INACTIVE,
                BinaryCheck.Parameter.Holdout.REGEX: "",
                BinaryCheck.Parameter.Holdout.PERCENTAGE: 100,
            },
            "threshold": 0.25,
        },
    )


class Migration(migrations.Migration):

    dependencies = []

    operations = [migrations.RunPython(create_abc_bank_name_velocity_fs, migrations.RunPython.noop)]
