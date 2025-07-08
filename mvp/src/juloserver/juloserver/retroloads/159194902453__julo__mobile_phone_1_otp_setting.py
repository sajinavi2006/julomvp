# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import migrations


from juloserver.julo.models import MobileFeatureSetting



def create_mobile_phone_1_otp_setting(apps, schema_editor):
    
    setting = MobileFeatureSetting(
        feature_name="mobile_phone_1_otp",
        parameters={'wait_time_seconds': 120})
    setting.save()


class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.RunPython(create_mobile_phone_1_otp_setting),
    ]
