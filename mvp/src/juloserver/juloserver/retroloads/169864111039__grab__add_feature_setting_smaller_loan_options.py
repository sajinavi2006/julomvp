# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2023-10-30 04:45
from __future__ import unicode_literals

from django.db import migrations

from juloserver.julo.constants import FeatureNameConst
from juloserver.julo.models import FeatureSetting


def create_feature_settings_smaller_loan_options(apps, _schema_editor):
    FeatureSetting.objects.create(
        feature_name=FeatureNameConst.GRAB_SMALLER_LOAN_OPTION,
        parameters={
            'min_loan_amount': 3500000,
            'range_to_max_gen_loan_amount': 2000000,
            'loan_option_range': ['30%', '60%'],
            'loan_tenure': 180
        },
        is_active=True,
        category="grab",
        description="setting for grab smaller loan options experiment"
    )


class Migration(migrations.Migration):
    dependencies = [
    ]

    operations = [
        migrations.RunPython(create_feature_settings_smaller_loan_options,
                             migrations.RunPython.noop),
    ]
