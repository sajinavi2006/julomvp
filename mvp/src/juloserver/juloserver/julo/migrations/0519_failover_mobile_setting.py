# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2019-03-28 07:36
from __future__ import unicode_literals

from django.db import migrations, models
import juloserver.julo.models

def failover_digisign_feature_mobile_setting(apps, schema_editor):
    MobileFeatureSetting = apps.get_model("julo", "MobileFeatureSetting")
    setting = MobileFeatureSetting(
        feature_name="failover_digisign",
        parameters={},
        is_active=True
    )
    setting.save()

class Migration(migrations.Migration):

    dependencies = [
        ('julo', '0518_handler_145'),
    ]

    operations = [
        migrations.RunPython(failover_digisign_feature_mobile_setting),
    ]
