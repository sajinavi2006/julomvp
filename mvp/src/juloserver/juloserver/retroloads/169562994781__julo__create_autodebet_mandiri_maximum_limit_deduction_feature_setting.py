# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2023-08-11 10:09
from __future__ import unicode_literals

from django.db import migrations

from juloserver.autodebet.constants import FeatureNameConst
from juloserver.julo.models import FeatureSetting


def create_autodebet_maximum_limit_deduction_feature_mandiri(apps, _schema_editor):
    FeatureSetting.objects.create(
        feature_name=FeatureNameConst.AUTODEBET_MANDIRI_MAX_LIMIT_DEDUCTION_DAY,
        parameters={
            "maximum_amount":5000000, 
            "deduction_dpd": [-1],
        },
        is_active=False,
        category="repayment",
        description="Autodebet Mandiri Maximum Limit Deduction Day"
    )


class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.RunPython(create_autodebet_maximum_limit_deduction_feature_mandiri,
                             migrations.RunPython.noop),
    ]
