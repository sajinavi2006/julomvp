# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2024-06-18 09:57
from __future__ import unicode_literals

from django.db import migrations

from juloserver.julo.models import FeatureSetting
from juloserver.channeling_loan.constants import FeatureNameConst as ChannelingFeatureNameConst


def add_feature_setting_loan_write_off(apps, schema_editor):
    FeatureSetting.objects.create(
        feature_name=ChannelingFeatureNameConst.LOAN_WRITE_OFF,
        is_active=False,
        parameters={
            "waiver": ['R4'],
            "restructure": [],
        },
    )


class Migration(migrations.Migration):

    dependencies = []

    operations = [
        migrations.RunPython(add_feature_setting_loan_write_off, migrations.RunPython.noop),
    ]
