# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2024-12-16 06:13
from __future__ import unicode_literals

from django.db import migrations
from juloserver.julo.models import FeatureSetting
from juloserver.fraud_score.constants import FeatureNameConst


def execute(apps, schema_editor):
    is_exist = FeatureSetting.objects.filter(feature_name=FeatureNameConst.MOCK_MONNAI_URL).exists()
    if not is_exist:
        FeatureSetting.objects.create(
            feature_name=FeatureNameConst.MOCK_MONNAI_URL,
            is_active=False,
            category='fraud',
            description='Feature to override the monnai url to the mock server in non-prod environment. If the value is empty, but the feature is active, then we will use actual url.',
            parameters={'MONNAI_AUTH_BASE_URL': '', 'MONNAI_INSIGHT_BASE_URL': ''},
        )


class Migration(migrations.Migration):

    dependencies = []

    operations = [migrations.RunPython(execute, migrations.RunPython.noop)]
