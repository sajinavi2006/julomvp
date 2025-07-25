# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2019-01-09 06:29
from __future__ import unicode_literals

from django.db import migrations
from juloserver.julo.constants import FeatureNameConst


from juloserver.julo.models import FeatureSetting



def add_advance_ai_check_settings(apps, schema_editor):
    
    FeatureSetting.objects.get_or_create(
        is_active=True,
        feature_name=FeatureNameConst.BLACKLIST_CHECK,
        category="experiment",
        parameters={},
        description="Function to automate ktp blacklist check by advance ai")

    FeatureSetting.objects.get_or_create(
        is_active=True,
        feature_name=FeatureNameConst.ID_CHECK,
        category="experiment",
        parameters={},
        description="Function to automate ktp id check by advance ai")


class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.RunPython(add_advance_ai_check_settings,
                             migrations.RunPython.noop)
    ]
