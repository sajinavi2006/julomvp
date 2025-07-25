# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2025-02-17 20:13
from __future__ import unicode_literals

from django.db import migrations

from juloserver.julo.constants import FeatureNameConst
from juloserver.julo.models import FeatureSetting


def create_feature_settings_antifraud_tokenize(apps, _schema_editor):
    feature_setting = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.ANTIFRAUD_PII_VAULT_TOKENIZATION
    )
    if not feature_setting.exists():
        FeatureSetting.objects.create(
            feature_name=FeatureNameConst.ANTIFRAUD_PII_VAULT_TOKENIZATION,
            is_active=False,
            category='fraud',
            description='This is feature setting for configure tokenization in antifraud',
        )


class Migration(migrations.Migration):
    dependencies = []

    operations = [
        migrations.RunPython(create_feature_settings_antifraud_tokenize, migrations.RunPython.noop)
    ]
