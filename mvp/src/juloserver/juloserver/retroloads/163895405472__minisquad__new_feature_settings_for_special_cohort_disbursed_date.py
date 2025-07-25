# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2021-12-08 09:00
from __future__ import unicode_literals

from django.db import migrations

from juloserver.julo.constants import FeatureNameConst
from juloserver.julo.models import FeatureSetting


def special_cohort_specific_loan_disburse(apps, schema_editor):
    FeatureSetting.objects.get_or_create(
        is_active=True,
        feature_name=FeatureNameConst.SPECIAL_COHORT_SPECIFIC_LOAN_DISBURSED_DATE,
        category="collection",
        # format month and year
        parameters={
            'start_month': '',
            'end_month': '',
            'year': ''
        },
        description="determine which payment goes to special cohort"
    )


class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.RunPython(
            special_cohort_specific_loan_disburse, migrations.RunPython.noop)
    ]
