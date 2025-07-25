# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2024-11-29 04:51
from __future__ import unicode_literals

from django.db import migrations

from juloserver.julo.models import FeatureSetting
from juloserver.loan.constants import LoanFeatureNameConst


def create_fs_qris_loan_eligibility_setting(app, schema_editor):
    parameters = {"max_requested_amount": 3_000_000}

    FeatureSetting.objects.update_or_create(
        feature_name=LoanFeatureNameConst.QRIS_LOAN_ELIGIBILITY_SETTING,
        defaults={
            'is_active': True,
            'category': 'qris',
            'description': 'Configurations for QRIS Loan Eligibility setting',
            'parameters': parameters,
        },
    )


class Migration(migrations.Migration):

    dependencies = []

    operations = [
        migrations.RunPython(
            code=create_fs_qris_loan_eligibility_setting,
            reverse_code=migrations.RunPython.noop,
        ),
    ]
