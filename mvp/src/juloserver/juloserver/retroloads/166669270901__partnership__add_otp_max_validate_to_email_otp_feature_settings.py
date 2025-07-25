# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2022-10-25 10:11
from __future__ import unicode_literals

from django.db import migrations
from juloserver.julo.models import FeatureSetting
from juloserver.julo.constants import FeatureNameConst


def add_otp_max_validate_to_email_otp_feature_setting(apps, schema_editor):
    feature_setting = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.EMAIL_OTP,
        is_active=True
    ).first()
    if feature_setting:
        feature_setting.parameters["otp_max_validate"] = 30
        feature_setting.save()
    else:
        created_data = {
            'feature_name': FeatureNameConst.EMAIL_OTP,
            'is_active': True,
            'parameters': {
                "otp_max_request": 30,
                "otp_max_validate": 3,
                "otp_resend_time": 30,
                "wait_time_seconds": 120
                },
            'category': 'partner',
            'description': 'Email OTP'
        }
        FeatureSetting.objects.create(**created_data)
        

class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.RunPython(add_otp_max_validate_to_email_otp_feature_setting, migrations.RunPython.noop),
    ]
