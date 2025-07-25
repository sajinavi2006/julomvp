# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2025-03-26 09:18
from __future__ import unicode_literals

from django.db import migrations
from juloserver.julo.constants import FeatureNameConst
from juloserver.julo.models import FeatureSetting


def execute(apps, schema_editor):
    is_exist = FeatureSetting.objects.filter(feature_name=FeatureNameConst.CROSS_OS_LOGIN).exists()
    if not is_exist:
        FeatureSetting.objects.create(
            feature_name=FeatureNameConst.CROSS_OS_LOGIN,
            category='application',
            is_active=True,
            description='Configuration for Cross OS login',
            parameters={'status_code': 'x190'},
        )


class Migration(migrations.Migration):

    dependencies = []

    operations = [
        migrations.RunPython(execute, migrations.RunPython.noop),
    ]
