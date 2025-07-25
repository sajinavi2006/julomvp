# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2023-05-17 09:29
from __future__ import unicode_literals

from django.db import migrations
from juloserver.julo.constants import FeatureNameConst

def add_loan_status_path_check(apps, schema_editor):
    FeatureSetting = apps.get_model("julo", "FeatureSetting")
    FeatureSetting.objects.get_or_create(
        is_active=False,
        feature_name=FeatureNameConst.LOAN_STATUS_PATH_CHECK,
        category="workload_status_path",
        description="Enable Status Path Checks (to workload_status_path table) on Loan status update",
    )

class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.RunPython(add_loan_status_path_check, migrations.RunPython.noop)
    ]
