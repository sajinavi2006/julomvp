# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2024-10-16 01:56
from __future__ import unicode_literals

from django.db import migrations
from juloserver.loan.constants import LoanFeatureNameConst
from juloserver.julo.models import FeatureSetting


def create_feature_settings_new_tenor_based_pricing(apps, _schema_editor):
    parameters = {
        'thresholds': {
            'data': {
                6: 0.01,
                9: 0.02,
                12: 0.05,
            },
            'is_active': True,
        },
        'minimum_pricing': {
            'data': 0.04,
            'is_active': True,
        },
        'cmr_segment': {
            'data': [],
            'is_active': False,
        },
        'transaction_methods': {
            'data': [1, 2],
            'is_active': True,
        }
    }
    FeatureSetting.objects.create(
         feature_name=LoanFeatureNameConst.NEW_TENOR_BASED_PRICING,
         parameters=parameters,
         category='loan',
         is_active=True,
         description="use tenor based New Pricing to replace CMR Pricing for user."
    )


class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
         migrations.RunPython(create_feature_settings_new_tenor_based_pricing, migrations.RunPython.noop)
    ]
