# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import migrations


def update_mobile_phone_1_otp_setting(apps, schema_editor):
    MobileFeatureSetting = apps.get_model("julo", "MobileFeatureSetting") 
    setting = MobileFeatureSetting.objects.filter(feature_name="mobile_phone_1_otp").first()
    setting.parameters={'wait_time_seconds': 300,'otp_max_request': 3, 'otp_resend_time': 60}
    setting.save()


class Migration(migrations.Migration):

    dependencies = [
        ('julo', '0537_add_table_centerix_callback_results'),
    ]

    operations = [
        migrations.RunPython(update_mobile_phone_1_otp_setting),
    ]
