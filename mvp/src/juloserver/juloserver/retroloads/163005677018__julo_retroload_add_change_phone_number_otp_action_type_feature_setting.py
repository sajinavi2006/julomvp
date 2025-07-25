# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2021-08-19 11:36
from __future__ import unicode_literals

from django.db import migrations
from juloserver.julo.models import FeatureSetting
from juloserver.otp.constants import SessionTokenAction, SessionTokenType


def add_change_phone_number_otp_action_type(apps, schema_editor):
    feature_setting = FeatureSetting.objects.get(feature_name='otp_action_type')
    parameters = feature_setting.parameters
    parameters.update({
        SessionTokenAction.CHANGE_PHONE_NUMBER: SessionTokenType.LONG_LIVED
    })
    feature_setting.save()


class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.RunPython(
            add_change_phone_number_otp_action_type, migrations.RunPython.noop),
    ]
