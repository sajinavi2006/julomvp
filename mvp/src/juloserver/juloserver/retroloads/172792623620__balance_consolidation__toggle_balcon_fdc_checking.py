# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2024-10-03 03:30
from __future__ import unicode_literals

from django.db import migrations
from juloserver.balance_consolidation.constants import FeatureNameConst
from juloserver.julo.models import FeatureSetting

def create_balance_consolidation_fdc_checking_fs(apps, schema_editor):
    FeatureSetting.objects.create(
        feature_name=FeatureNameConst.BALANCE_CONSOLIDATION_FDC_CHECKING,
        category="balance_consolidation",
        description="Turn on/off for Balance Consolidation FDC checking flow",
        is_active=False,
        parameters={
            'start_date': ''
        },
    )


class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.RunPython(
            create_balance_consolidation_fdc_checking_fs, migrations.RunPython.noop
        ),
    ]
