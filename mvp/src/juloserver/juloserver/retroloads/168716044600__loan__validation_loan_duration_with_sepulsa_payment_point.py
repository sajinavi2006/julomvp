# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2023-06-19 07:40
from __future__ import unicode_literals

from django.db import migrations

from juloserver.julo.constants import FeatureNameConst
from juloserver.julo.models import FeatureSetting


def add_validate_loan_duration_with_sepulsa_payment_point_feature_setting(_apps, _schema_editor):
    FeatureSetting.objects.create(
        feature_name=FeatureNameConst.VALIDATE_LOAN_DURATION_WITH_SEPULSA_PAYMENT_POINT,
        is_active=False,
        parameters=None,
        category='Loan',
        description='Validate loan duration request body match with Sepulsa payment point tracking '
                    'for all Sepulsa product',
    )


class Migration(migrations.Migration):
    dependencies = [
    ]

    operations = [
        migrations.RunPython(add_validate_loan_duration_with_sepulsa_payment_point_feature_setting,
                             migrations.RunPython.noop),
    ]
