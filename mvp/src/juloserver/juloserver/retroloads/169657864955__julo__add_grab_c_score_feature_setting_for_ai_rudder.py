# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2023-10-06 07:50
from __future__ import unicode_literals

from django.db import migrations
from juloserver.julo.models import FeatureSetting
from juloserver.julo.constants import FeatureNameConst
from juloserver.minisquad.constants import AiRudder
from juloserver.minisquad.constants import FeatureNameConst as FeatureNameConst1


def add_grab_c_score_feature_settings(apps, _schema_editor):
    if not FeatureSetting.objects.\
            filter(feature_name=FeatureNameConst.GRAB_C_SCORE_FEATURE_FOR_AI_RUDDER).\
            exists():
        FeatureSetting.objects.create(
            feature_name=FeatureNameConst.GRAB_C_SCORE_FEATURE_FOR_AI_RUDDER,
            is_active=False,
            description="Grab C-Score - On/Off Grab c-score feature for ai_rudder",
            category='grab'
        )
        new_parameters = {
            AiRudder.GRAB: 5000,
        }
        feature_setting = FeatureSetting.objects.get_or_none(
            feature_name=FeatureNameConst1.AI_RUDDER_SEND_BATCHING_THRESHOLD
        )
        if not feature_setting:
            return
        existing_param = feature_setting.parameters
        existing_param.update(new_parameters)
        feature_setting.parameters = existing_param
        feature_setting.save()


class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.RunPython(add_grab_c_score_feature_settings, migrations.RunPython.noop)
    ]
