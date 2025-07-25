# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2025-02-21 07:00
from __future__ import unicode_literals

from django.db import migrations

from juloserver.julo.models import FeatureSetting
from juloserver.loan.constants import LoanFeatureNameConst


def add_fs_qris_error_logging(app, schema_editor):
    fs = FeatureSetting.objects.filter(
        feature_name=LoanFeatureNameConst.QRIS_ERROR_LOG,
    ).last()

    if not fs:
        FeatureSetting.objects.create(
            feature_name=LoanFeatureNameConst.QRIS_ERROR_LOG,
            is_active=True,
            category='qris',
            description='logging payload/validation errors for qris',
        )


class Migration(migrations.Migration):

    dependencies = []

    operations = [
        migrations.RunPython(
            code=add_fs_qris_error_logging,
            reverse_code=migrations.RunPython.noop,
        ),
    ]
