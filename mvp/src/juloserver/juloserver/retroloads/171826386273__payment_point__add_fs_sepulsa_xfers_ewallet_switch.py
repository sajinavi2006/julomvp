# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2024-06-13 07:31
from __future__ import unicode_literals

from django.db import migrations

from juloserver.julo.models import FeatureSetting
from juloserver.payment_point.constants import FeatureNameConst as PaymentPointFeatureNameConst


def add_fs_sepulsa_xfers_ewallet(apps, schema_editor):
    params = {
        "is_whitelist_active": True,
        'whitelist_customer_ids': [],
    }

    FeatureSetting.objects.update_or_create(
        feature_name=PaymentPointFeatureNameConst.SEPULSA_XFERS_EWALLET_SWITCH,
        defaults={
            'is_active': False,
            'category': 'payment_point',
            'description': 'Configurations for switching sepulsa and xfers ewallet',
            'parameters': params,
        },
    )


class Migration(migrations.Migration):

    dependencies = []

    operations = [
        migrations.RunPython(
            code=add_fs_sepulsa_xfers_ewallet,
            reverse_code=migrations.RunPython.noop,
        ),
    ]
