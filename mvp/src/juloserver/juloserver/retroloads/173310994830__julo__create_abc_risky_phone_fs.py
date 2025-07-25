# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2024-12-02 03:25
from __future__ import unicode_literals

from django.db import migrations
from juloserver.julo.models import FeatureSetting
from juloserver.antifraud.constant.feature_setting import BinaryCheck, Holdout


def create_fs_antifraud_risky_phone_email(apps, _schema_editor):
    feature_setting = FeatureSetting.objects.filter(
        feature_name='abc_risky_phone_and_email'
    )

    if not feature_setting.exists():
        FeatureSetting.objects.create(
            feature_name='abc_risky_phone_and_email',
            is_active=False,
            category="antifraud",
            description="Feature Flag for antifraud binary check risky phone and email",
            parameters={
                BinaryCheck.Parameter.HOLDOUT: {
                    BinaryCheck.Parameter.Holdout.TYPE: Holdout.Type.INACTIVE,
                    BinaryCheck.Parameter.Holdout.REGEX: "",
                    BinaryCheck.Parameter.Holdout.PERCENTAGE: 100,
                    BinaryCheck.Parameter.Holdout.PARTNER_IDS: [],
                },
                "threshold": {
                    "mycroft_rule_1":0.9,
                    "mycroft_rule_2":0.9
                }
            },
        )

    feature_setting_jturbo = FeatureSetting.objects.filter(
        feature_name='abc_risky_phone_and_email_jturbo'
    )

    if not feature_setting_jturbo.exists():
        FeatureSetting.objects.create(
            feature_name='abc_risky_phone_and_email_jturbo',
            is_active=False,
            category="antifraud",
            description="Feature Flag for antifraud binary check risky phone and email for jturbo",
            parameters={
                BinaryCheck.Parameter.HOLDOUT: {
                    BinaryCheck.Parameter.Holdout.TYPE: Holdout.Type.INACTIVE,
                    BinaryCheck.Parameter.Holdout.REGEX: "",
                    BinaryCheck.Parameter.Holdout.PERCENTAGE: 100,
                    BinaryCheck.Parameter.Holdout.PARTNER_IDS: [],
                },
                "threshold": {
                    "mycroft_rule_1":0.9,
                    "mycroft_rule_2":0.9
                }
            },
        )


class Migration(migrations.Migration):

    dependencies = []

    operations = [
        migrations.RunPython(create_fs_antifraud_risky_phone_email, migrations.RunPython.noop)
    ]
