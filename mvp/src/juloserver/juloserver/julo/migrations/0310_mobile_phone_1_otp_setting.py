# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import migrations


def create_mobile_phone_1_otp_setting(apps, schema_editor):
    MobileFeatureSetting = apps.get_model("julo", "MobileFeatureSetting")
    setting = MobileFeatureSetting(
        feature_name="mobile_phone_1_otp",
        parameters={'wait_time_seconds': 120})
    setting.save()


class Migration(migrations.Migration):

    dependencies = [
        ('julo', '0309_auto_call_138_feature_setting'),
    ]

    operations = [
        migrations.RunPython(create_mobile_phone_1_otp_setting),
    ]
