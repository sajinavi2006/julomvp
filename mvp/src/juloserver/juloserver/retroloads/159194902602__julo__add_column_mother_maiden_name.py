# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2019-12-06 00:01
from __future__ import unicode_literals

from django.conf import settings
import django.core.validators
from django.db import migrations, models
import django.db.models.deletion
from juloserver.julo.models import MobileFeatureSetting


class Migration(migrations.Migration):


    def create_mother_maiden_name_setting(apps, schema_editor):
        
        setting = MobileFeatureSetting(
            feature_name="mother_maiden_name",
            parameters={},
            is_active=True
        )
        setting.save()

    dependencies = [
    ]

    operations = [
        migrations.RunPython(create_mother_maiden_name_setting),
    ]
