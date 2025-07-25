# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2025-01-16 08:29
from __future__ import unicode_literals

from django.db import migrations
from juloserver.julo.models import FeatureSetting
from juloserver.minisquad.constants import FeatureNameConst


def add_voice_mail_configuration(apps, schema_editor):
    feature_group_mapping_config = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.AI_RUDDER_TASKS_STRATEGY_CONFIG
    ).last()
    if not feature_group_mapping_config:
        return

    params = feature_group_mapping_config.parameters
    for bucket_name, value in params.items():
        configuration_per_bucket = value
        configuration_per_bucket.update(voicemailRedial=0)
        params.update({bucket_name: configuration_per_bucket})
    feature_group_mapping_config.parameters = params
    feature_group_mapping_config.save()


class Migration(migrations.Migration):

    dependencies = []

    operations = [migrations.RunPython(add_voice_mail_configuration, migrations.RunPython.noop)]
