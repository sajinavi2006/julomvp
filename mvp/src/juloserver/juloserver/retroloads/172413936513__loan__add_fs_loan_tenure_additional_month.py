# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2024-08-20 07:36
from __future__ import unicode_literals

from django.db import migrations

from juloserver.julo.models import FeatureSetting
from juloserver.loan.constants import LoanFeatureNameConst


def add_fs_loan_tenure_additional_month(apps, schema_editor):
    params = {
        'whitelist': {
            'is_active': True,
            'customer_ids': [],
        },
        'additional_month': 10,
    }

    FeatureSetting.objects.update_or_create(
        feature_name=LoanFeatureNameConst.LOAN_TENURE_ADDITIONAL_MONTH,
        defaults={
            'is_active': False,
            'category': 'loan',
            'description': 'Loan Tenure Additional Month Settings',
            'parameters': params,
        },
    )


class Migration(migrations.Migration):

    dependencies = []

    operations = [
        migrations.RunPython(
            code=add_fs_loan_tenure_additional_month,
            reverse_code=migrations.RunPython.noop,
        ),
    ]
