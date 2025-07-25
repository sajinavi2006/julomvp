# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2024-03-28 07:15
from __future__ import unicode_literals

from django.db import migrations
from juloserver.julo.models import FeatureSetting
from juloserver.julo.constants import FeatureNameConst

from juloserver.sales_ops.constants import SalesOpsSettingConst


def update_sales_ops_feature_setting_parameters(app, __schema_editor):
    fs = FeatureSetting.objects.get_or_none(feature_name=FeatureNameConst.SALES_OPS)
    if not fs:
        return

    to_be_deteled_keys = [
        'autodial_non_rpc_attempt_count',
        'autodial_non_rpc_delay_hour',
        'autodial_non_rpc_final_delay_hour',
        'autodial_rpc_delay_hour',
        'lineup_rpc_delay_hour'
    ]

    parameters = fs.parameters
    for key in to_be_deteled_keys:
        if key in parameters:
            del parameters[key]

    parameters[SalesOpsSettingConst.LINEUP_AND_AUTODIAL_NON_RPC_ATTEMPT_COUNT] = \
        SalesOpsSettingConst.DEFAULT_LINEUP_AND_AUTODIAL_NON_RPC_ATTEMPT_COUNT
    parameters[SalesOpsSettingConst.LINEUP_AND_AUTODIAL_NON_RPC_DELAY_HOUR] = \
        SalesOpsSettingConst.DEFAULT_LINEUP_AND_AUTODIAL_NON_RPC_DELAY_HOUR
    parameters[SalesOpsSettingConst.LINEUP_AND_AUTODIAL_NON_RPC_FINAL_DELAY_HOUR] = \
        SalesOpsSettingConst.DEFAULT_LINEUP_AND_AUTODIAL_NON_RPC_FINAL_DELAY_HOUR
    parameters[SalesOpsSettingConst.LINEUP_AND_AUTODIAL_RPC_DELAY_HOUR] = \
        SalesOpsSettingConst.DEFAULT_LINEUP_AND_AUTODIAL_RPC_DELAY_HOUR

    fs.update_safely(parameters=parameters)


class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.RunPython(
            update_sales_ops_feature_setting_parameters, migrations.RunPython.noop
        ),
    ]
