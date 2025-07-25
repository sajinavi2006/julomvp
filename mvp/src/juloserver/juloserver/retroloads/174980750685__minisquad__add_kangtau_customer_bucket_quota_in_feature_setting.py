# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2025-06-13 09:38
from __future__ import unicode_literals

from django.db import migrations

from juloserver.julo.models import FeatureSetting


def insert_data(apps, schema_editor):
    FeatureSetting.objects.create(
        feature_name='kangtau_customer_bucket_quota',
        category='kangtau',
        description='Quota on the number of customer data entries per bucket uploaded to Kangtau',
        parameters={
            'buckets': [
                {'B0': 3500},
                {'B1': 2000},
                {'B2': 14050},
                {'B3': 14050},
                {'B4': 14050},
                {'B5': 81000},
            ]
        },
    )


class Migration(migrations.Migration):

    dependencies = []

    operations = [migrations.RunPython(insert_data)]
