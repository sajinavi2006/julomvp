# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2024-11-21 02:54
from __future__ import unicode_literals

from django.db import migrations
from juloserver.julo.models import FeatureSetting
from juloserver.minisquad.constants import FeatureNameConst


def add_feature_setting_to_merge_current_j1_and_jturbo_bucket_current(apps, schema_editor):
    params = (
        FeatureSetting.objects.filter(
            feature_name=FeatureNameConst.AI_RUDDER_FULL_ROLLOUT, is_active=True
        )
        .get()
        .parameters
    )
    if params:
        bucket_numbers_to_merge = params['bucket_numbers_to_merge'] + [0, -1, -3, -5]
        params['bucket_numbers_to_merge'] = bucket_numbers_to_merge
        FeatureSetting.objects.filter(feature_name=FeatureNameConst.AI_RUDDER_FULL_ROLLOUT).update(
            parameters=params
        )


class Migration(migrations.Migration):
    dependencies = []
    operations = [
        migrations.RunPython(
            add_feature_setting_to_merge_current_j1_and_jturbo_bucket_current,
            migrations.RunPython.noop,
        )
    ]
