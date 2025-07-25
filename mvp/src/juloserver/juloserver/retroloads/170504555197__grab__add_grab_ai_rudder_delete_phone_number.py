# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2024-01-12 07:45
from __future__ import unicode_literals

from django.db import migrations
from juloserver.julo.models import FeatureSetting
from juloserver.julo.constants import FeatureNameConst


def add_grab_ai_rudder_delete_phone_number_settings(apps, _schema_editor):
    if not FeatureSetting.objects.\
            filter(feature_name=FeatureNameConst.GRAB_AI_RUDDER_DELETE_PHONE_NUMBER).\
            exists():
        FeatureSetting.objects.create(
            feature_name=FeatureNameConst.GRAB_AI_RUDDER_DELETE_PHONE_NUMBER,
            is_active=False,
            description="Grab - Ai Rudder delete phone number",
            category='grab'
        )


class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.RunPython(add_grab_ai_rudder_delete_phone_number_settings, migrations.RunPython.noop)
    ]
