# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2024-10-27 19:56
from __future__ import unicode_literals

from django.db import migrations
from juloserver.account_payment.constants import FeatureNameConst
from juloserver.julo.models import FeatureSetting


def add_automate_late_fee_void_feature_settings(apps, schema_editor):
    FeatureSetting.objects.get_or_create(
        is_active=True,
        feature_name=FeatureNameConst.AUTOMATE_LATE_FEE_VOID,
        category="repayment",
        parameters={"days_threshold": 3},
        description="feature to set automate late fee void",
    )


class Migration(migrations.Migration):

    dependencies = []

    operations = [
        migrations.RunPython(add_automate_late_fee_void_feature_settings, migrations.RunPython.noop)
    ]
