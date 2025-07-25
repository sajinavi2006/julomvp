# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2024-11-19 03:31
from __future__ import unicode_literals

from django.db import migrations
from juloserver.julo.models import FeatureSetting
from juloserver.minisquad.constants import FeatureNameConst
from juloserver.minisquad.constants import BTTCExperiment


def add_julo_gold_configuration_for_bcurrent(apps, schema_editor):
    bucket_currents = ['JULO_T0', 'JULO_T-1', 'JULO_T-3', 'JULO_T-5']
    bucket_names_bttc_current = []
    ranges_exp = ['a', 'b', 'c', 'd']
    for range_exp in ranges_exp:
        bucket_names_bttc_current.append(
            BTTCExperiment.BASED_CURRENT_BUCKET_NAME.format(3, range_exp.upper())
        )

    bucket_currents.extend(bucket_names_bttc_current)
    # create new airudder configuration for bucket related
    feature_group_mapping_config = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.AI_RUDDER_TASKS_STRATEGY_CONFIG
    ).last()
    if not feature_group_mapping_config:
        return

    params = feature_group_mapping_config.parameters
    for bucket_name in bucket_currents:
        configuration_per_bucket = params.get(bucket_name)
        configuration_per_bucket.update(julo_gold_status='exclude')
        params.update({bucket_name: configuration_per_bucket})
    feature_group_mapping_config.parameters = params
    feature_group_mapping_config.save()


class Migration(migrations.Migration):

    dependencies = []

    operations = [
        migrations.RunPython(add_julo_gold_configuration_for_bcurrent, migrations.RunPython.noop)
    ]
