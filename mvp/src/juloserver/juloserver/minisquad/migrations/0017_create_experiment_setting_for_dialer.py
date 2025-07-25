# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2019-10-17 03:16
from __future__ import unicode_literals
from juloserver.julo.constants import ExperimentConst
from juloserver.minisquad.constants import DialerVendor
from django.db import migrations


def add_experiment_setting_for_dialer(apps, schema_editor):
    ExperimentSetting = apps.get_model("julo", "ExperimentSetting")
    ExperimentSetting.objects.create(
        is_active=True,
        code=ExperimentConst.COLLECTION_NEW_DIALER_V1,
        name="Dialer Experiment",
        start_date="2020-05-26 00:00:00+00",
        end_date="2020-06-11 00:00:00+00",
        schedule="",
        action="",
        type="payment",
        criteria={
            DialerVendor.CENTERIX: [0, 49],
            DialerVendor.INTELIX: [50, 99]
        })


class Migration(migrations.Migration):

    dependencies = [
        ('minisquad', '0016_create_vendorqualityexperiment_table'),
    ]

    operations = [
        migrations.RunPython(add_experiment_setting_for_dialer, migrations.RunPython.noop)

    ]
