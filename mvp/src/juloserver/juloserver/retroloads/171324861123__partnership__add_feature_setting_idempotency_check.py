# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2024-04-16 06:23
from __future__ import unicode_literals

from django.db import migrations
from juloserver.julo.constants import FeatureNameConst
from juloserver.julo.models import FeatureSetting


def add_feature_setting_idempotency_check(apps, _schema_editor):
    data_to_be_created = {
        'feature_name': FeatureNameConst.PARTNERSHIP_IDEMPOTENCY_CHECK,
        'is_active': True,
        'parameters': {},
        'category': 'partnership',
        'description': 'This configuration is used to block idempotency check',
    }
    FeatureSetting.objects.create(**data_to_be_created)


class Migration(migrations.Migration):
    dependencies = []

    operations = [
        migrations.RunPython(add_feature_setting_idempotency_check, migrations.RunPython.noop)
    ]
