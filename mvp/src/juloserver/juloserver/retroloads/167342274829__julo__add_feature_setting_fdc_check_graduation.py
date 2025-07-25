# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2023-01-11 07:39
from __future__ import unicode_literals

from django.db import migrations

from juloserver.graduation.constants import FeatureNameConst
from juloserver.julo.models import FeatureSetting


def create_fdc_check_graduation(apps, _schema_editor):
    FeatureSetting.objects.create(
        feature_name=FeatureNameConst.GRADUATION_FDC_CHECK,
        is_active=True,
        parameters='',
        category='graduation',
        description='Feature Setting to turn off/on FDC Check for Graduation'
    )


class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.RunPython(create_fdc_check_graduation, migrations.RunPython.noop)
    ]
