# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2023-05-17 02:24
from __future__ import unicode_literals

from django.db import migrations

from juloserver.early_limit_release.constants import FeatureNameConst
from juloserver.julo.models import FeatureSetting


def create_early_limit_release_feature_setting(apps, _schema_editor):
    FeatureSetting.objects.create(
        feature_name=FeatureNameConst.EARLY_LIMIT_RELEASE,
        is_active=False,
        parameters={},
        description='Setting to turn on/off early limit release feature',
        category='early_limit_release'
    )


class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.RunPython(create_early_limit_release_feature_setting, migrations.RunPython.noop),
    ]
