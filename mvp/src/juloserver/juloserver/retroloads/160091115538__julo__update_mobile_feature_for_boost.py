# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2020-09-24 01:32
from __future__ import unicode_literals
from juloserver.julo.models import MobileFeatureSetting
from django.db import migrations
import json


def update_mobile_feature_seetings_for_boost(apps, _schema_editor):
    boost_settings = MobileFeatureSetting.objects.filter(feature_name='boost',
                                                         is_active=True).last()
    parameters = {"julo_one": {"is_active": True},
                  "bank": {"bni": {"is_active": True}, "is_active": True,
                           "bca": {"is_active": True}, "bri": {"is_active": True},
                           "mandiri": {"is_active": True}},
                  "bpjs": {"is_active": True}}
    boost_settings.parameters = json.dumps(parameters)
    boost_settings.save()


class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.RunPython(update_mobile_feature_seetings_for_boost, migrations.RunPython.noop),
    ]
