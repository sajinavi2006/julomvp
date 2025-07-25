# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2023-12-19 17:34
from __future__ import unicode_literals

from django.db import migrations
from juloserver.julo.models import FeatureSetting
from juloserver.julo.constants import FeatureNameConst


def add_grab_manual_upload_airudder_feature_settings(apps, _schema_editor):
    if not FeatureSetting.objects.\
            filter(feature_name=FeatureNameConst.GRAB_MANUAL_UPLOAD_FEATURE_FOR_AI_RUDDER).\
            exists():
        FeatureSetting.objects.create(
            feature_name=FeatureNameConst.GRAB_MANUAL_UPLOAD_FEATURE_FOR_AI_RUDDER,
            is_active=False,
            description="Grab manual upload - On/Off Grab manual upload feature for ai_rudder",
            category='grab'
        )


class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.RunPython(add_grab_manual_upload_airudder_feature_settings, migrations.RunPython.noop)
    ]
