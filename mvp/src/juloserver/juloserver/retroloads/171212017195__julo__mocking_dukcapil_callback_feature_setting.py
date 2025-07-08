# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import migrations
import datetime
from juloserver.julo.constants import FeatureNameConst

from juloserver.julo.models import FeatureSetting


def mocking_dukcapil_callback_feature_setting(apps, _schema_editor):

    dukcapil_response = {'message': 'Success'}

    FeatureSetting.objects.get_or_create(
        is_active=True,
        feature_name=FeatureNameConst.DUKCAPIL_CALLBACK_MOCK_RESPONSE_SET,
        category="mocking_response",
        parameters={
            "product": [
                "j-starter",
                "j1",
            ],
            "latency": 1000,
            "response": dukcapil_response,
            "response_status": 200,
            "response_status": 200,
            "response_message": "Success",
        },
        description="Config Dukcapil Callback mocking response",
    )


class Migration(migrations.Migration):

    dependencies = []

    operations = [
        migrations.RunPython(mocking_dukcapil_callback_feature_setting, migrations.RunPython.noop)
    ]
