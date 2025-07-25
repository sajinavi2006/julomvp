# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2024-06-18 09:10
from __future__ import unicode_literals

from django.db import migrations

from juloserver.julo.models import FeatureSetting
from juloserver.channeling_loan.constants import (
    FeatureNameConst as ChannelingFeatureNameConst,
    ChannelingConst,
)


def add_channeling_loan_filename_counter_suffix_config(apps, schema_editor):
    channeling_loan_fs = FeatureSetting.objects.filter(
        feature_name=ChannelingFeatureNameConst.CHANNELING_LOAN_CONFIG,
    ).last()
    if not channeling_loan_fs:
        return

    for channeling_type, _ in channeling_loan_fs.parameters.items():
        channeling_loan_fs.parameters[channeling_type]['filename_counter_suffix'] = {
            'is_active': False,
            'LENGTH': 0,
        }

    channeling_loan_fs.parameters[ChannelingConst.FAMA]['filename_counter_suffix'] = {
        'is_active': True,
        'LENGTH': 2,
    }

    channeling_loan_fs.save()


class Migration(migrations.Migration):

    dependencies = []

    operations = [
        migrations.RunPython(
            add_channeling_loan_filename_counter_suffix_config, migrations.RunPython.noop
        )
    ]
