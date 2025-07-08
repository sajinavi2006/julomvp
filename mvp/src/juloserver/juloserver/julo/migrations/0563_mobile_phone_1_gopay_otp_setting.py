# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import migrations


def create_mobile_phone_1_otp_setting(apps, schema_editor):
    MobileFeatureSetting = apps.get_model("julo", "MobileFeatureSetting")
    setting = MobileFeatureSetting(
        feature_name="mobile_phone_1_gopay_otp",
        parameters={'wait_time_seconds': 300,'otp_max_request': 3, 'otp_resend_time': 60})
    setting.save()


class Migration(migrations.Migration):

    dependencies = [
        ('julo', '0562_add_experiment_for_CeM_b2_b3_b4'),
    ]

    operations = [
        migrations.RunPython(create_mobile_phone_1_otp_setting),
    ]
