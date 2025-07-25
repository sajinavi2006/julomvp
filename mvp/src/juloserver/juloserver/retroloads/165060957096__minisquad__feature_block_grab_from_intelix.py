# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2022-04-22 06:39
from __future__ import unicode_literals

from django.db import migrations

from juloserver.julo.models import FeatureSetting
from juloserver.minisquad.constants import FeatureNameConst


def add_new_feature_settings_allow_multiple_va(apps, _schema_editor):
    FeatureSetting.objects.create(
        feature_name=FeatureNameConst.TAKING_OUT_GRAB_FROM_INTELIX,
        is_active=True,
        parameters={},
        category='dialer',
        description="Configure Send or not grab bucket to dialer")

class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.RunPython(add_new_feature_settings_allow_multiple_va,
                             migrations.RunPython.noop)
    ]
