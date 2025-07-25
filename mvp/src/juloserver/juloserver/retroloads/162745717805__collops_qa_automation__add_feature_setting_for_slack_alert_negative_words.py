# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2021-07-28 07:26
from __future__ import unicode_literals

from django.db import migrations

from juloserver.julo.constants import FeatureNameConst
from juloserver.julo.models import FeatureSetting


def add_slack_negative_words_feature_setting(apps, schema_editor):
    FeatureSetting.objects.get_or_create(
        is_active=True,
        feature_name=FeatureNameConst.SLACK_NOTIFICATION_NEGATIVE_WORDS_THRESHOLD,
        category="collection",
        parameters={
            "negative_words_threshold": 10,
            "threshold_type": ">=",
            "channel": "#call_negative_words_alert"
        },
        description="for setting threshold and alert slack when negative words reach threshold")


class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.RunPython(add_slack_negative_words_feature_setting,
                             migrations.RunPython.noop)
    ]
