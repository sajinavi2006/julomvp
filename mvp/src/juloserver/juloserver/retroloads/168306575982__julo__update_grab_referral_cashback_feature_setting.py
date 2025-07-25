# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2023-05-02 22:15
from __future__ import unicode_literals

from django.db import migrations
from juloserver.julo.constants import FeatureNameConst

from juloserver.julo.models import FeatureSetting


def add_new_grab_referral_program_feature_setting_parameters(apps, _schema_editor):
    new_parameters = {
        "referrer_incentive": 50000,
        "referred_incentive": 30000
    }
    grab_referral_program = FeatureSetting.objects.get_or_none(feature_name=FeatureNameConst.GRAB_REFERRAL_PROGRAM)
    if not grab_referral_program:
        return
    
    existing_param = grab_referral_program.parameters
    existing_param.update(new_parameters)
    grab_referral_program.update_safely(parameters = existing_param)


class Migration(migrations.Migration):
    dependencies = [
    ]

    operations = [
        migrations.RunPython(add_new_grab_referral_program_feature_setting_parameters, migrations.RunPython.noop),
    ]
