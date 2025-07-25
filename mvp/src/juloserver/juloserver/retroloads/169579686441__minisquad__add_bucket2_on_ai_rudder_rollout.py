# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2023-09-27 06:41
from __future__ import unicode_literals

from django.db import migrations

from juloserver.julo.models import FeatureSetting
from juloserver.minisquad.constants import (
    FeatureNameConst,
    DialerSystemConst,
)


def add_bucket_2_to_ai_rudder_feature_setting(apps, schema_editor):
    feature_group_mapping_config = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.AI_RUDDER_FULL_ROLLOUT).last()
    if not feature_group_mapping_config:
        return
    feature_group_mapping_config.refresh_from_db()
    params = feature_group_mapping_config.parameters
    eligible_buckets = params['eligible_bucket_number']
    eligible_buckets.append(2)
    params['eligible_bucket_number'] = eligible_buckets
    feature_group_mapping_config.parameters = params
    feature_group_mapping_config.save()

    feature_batching_threshold_group_config = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.AI_RUDDER_SEND_BATCHING_THRESHOLD).last()
    if not feature_batching_threshold_group_config:
        return

    params_threshold = feature_batching_threshold_group_config.parameters
    params_threshold[DialerSystemConst.DIALER_BUCKET_2] = 5000
    params_threshold[DialerSystemConst.DIALER_BUCKET_2_NC] = 5000
    feature_batching_threshold_group_config.parameters = params_threshold
    feature_batching_threshold_group_config.save()

    feature_slack_alert = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.AI_RUDDER_SEND_SLACK_ALERT).last()
    if not feature_slack_alert:
        return

    params_slack_alert = feature_slack_alert.parameters
    bucket_list = params_slack_alert['bucket_list']
    bucket_list.append(DialerSystemConst.DIALER_BUCKET_2)
    bucket_list.append(DialerSystemConst.DIALER_BUCKET_2_NC)
    params_slack_alert['bucket_list'] = bucket_list
    feature_slack_alert.parameters = params_slack_alert
    feature_slack_alert.save()

    feature_group_config = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.AI_RUDDER_GROUP_NAME_CONFIG).last()
    if not feature_group_config:
        return

    params_feature_group_config = feature_group_config.parameters
    params_feature_group_config[DialerSystemConst.DIALER_BUCKET_2] = "Group_Bucket2"
    params_feature_group_config[DialerSystemConst.DIALER_BUCKET_2_NC] = "Group_Bucket2"
    feature_group_config.parameters = params_feature_group_config
    feature_group_config.save()

    feature_ai_rudder_tasks_config = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.AI_RUDDER_TASKS_STRATEGY_CONFIG).last()
    if feature_ai_rudder_tasks_config:
        return

    feature_ai_rudder_tasks_config_params = feature_ai_rudder_tasks_config.parameters
    b3_config = feature_ai_rudder_tasks_config_params[DialerSystemConst.DIALER_BUCKET_3]
    feature_ai_rudder_tasks_config_params[DialerSystemConst.DIALER_BUCKET_2] = b3_config
    feature_ai_rudder_tasks_config_params[DialerSystemConst.DIALER_BUCKET_2_NC] = b3_config
    feature_ai_rudder_tasks_config.parameters = feature_ai_rudder_tasks_config_params
    feature_ai_rudder_tasks_config.save()


class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.RunPython(add_bucket_2_to_ai_rudder_feature_setting, migrations.RunPython.noop)
    ]
