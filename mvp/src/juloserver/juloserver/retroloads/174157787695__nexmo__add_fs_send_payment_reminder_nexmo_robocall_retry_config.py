# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2025-03-10 03:37
from __future__ import unicode_literals

from django.db import migrations

from juloserver.julo.models import FeatureSetting
from juloserver.nexmo.models import NexmoSendConfig


def run(apps, schema_editor):
    if FeatureSetting.objects.filter(
        feature_name=NexmoSendConfig.FEATURE_NEXMO_RETRY_CONFIG
    ).exists():
        return

    FeatureSetting.objects.create(
        feature_name=NexmoSendConfig.FEATURE_NEXMO_RETRY_CONFIG,
        category="omnichannel",
        description="send_payment_reminder_nexmo_robocall retry config",
        is_active=False,
        parameters={"max_retry": 60, "mock_retry": False, "mock_num_retry": 60},
    )


class Migration(migrations.Migration):

    dependencies = []

    operations = [migrations.RunPython(run, migrations.RunPython.noop)]
