# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2024-05-13 13:31
from __future__ import unicode_literals

from django.db import migrations

from juloserver.sales_ops.constants import SalesOpsAlert
from juloserver.julo.constants import FeatureNameConst
from juloserver.julo.models import FeatureSetting


def init_sales_ops_alerts_feature_setting_parameters(app, __schema_editor):
    parameters = {
        'success_message': '<!here> Today init sales ops lineup data is successful. ',
        'failure_message': '<!here> Today init sales ops lineup data is failed. ' \
                           'Please check!',
        'channel': SalesOpsAlert.CHANNEL
    }

    FeatureSetting.objects.create(
        feature_name=FeatureNameConst.SALES_OPS_ALERT,
        is_active=True,
        parameters=parameters,
        category='sales_ops',
        description='Feature Setting to send sales ops notification to Slack'
    )


class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.RunPython(
            init_sales_ops_alerts_feature_setting_parameters, migrations.RunPython.noop
        ),
    ]
