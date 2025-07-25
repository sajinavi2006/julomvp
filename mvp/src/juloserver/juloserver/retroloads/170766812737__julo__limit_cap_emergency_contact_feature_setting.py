# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2024-02-06 05:34
from __future__ import unicode_literals

from django.db import migrations
from juloserver.julo.constants import FeatureNameConst
from juloserver.julo.models import FeatureSetting


def run(apps, schema_editor):
    if not FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.LIMIT_CAP_EMERGENCY_CONTACT
    ).exists():
        FeatureSetting.objects.create(
            feature_name=FeatureNameConst.LIMIT_CAP_EMERGENCY_CONTACT,
            is_active=True,
            category='application',
            description='limit cap percentage setting for non consented emergency contact ',
            parameters={
                'limit_cap_percentage': 80
            }
        )


class Migration(migrations.Migration):
    dependencies = [
    ]

    operations = [
        migrations.RunPython(run, migrations.RunPython.noop),
    ]
