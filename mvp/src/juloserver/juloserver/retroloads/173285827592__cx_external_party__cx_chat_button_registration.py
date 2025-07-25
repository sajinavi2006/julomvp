# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2024-11-29 05:31
from __future__ import unicode_literals

from django.db import migrations

from juloserver.julo.constants import MobileFeatureNameConst
from juloserver.julo.models import MobileFeatureSetting


def add_fs_cx_live_chat_registration_form(apps, schema_editor):
    is_exist = MobileFeatureSetting.objects.filter(
        feature_name=MobileFeatureNameConst.CX_LIVE_CHAT_REGISTRATION_FORM
    ).exists()
    if not is_exist:
        MobileFeatureSetting.objects.create(
            feature_name=MobileFeatureNameConst.CX_LIVE_CHAT_REGISTRATION_FORM,
            is_active=True,
            parameters={"show_delay": 30, "hide_delay": 120},
        )


class Migration(migrations.Migration):
    dependencies = []

    operations = [
        migrations.RunPython(add_fs_cx_live_chat_registration_form, migrations.RunPython.noop),
    ]
