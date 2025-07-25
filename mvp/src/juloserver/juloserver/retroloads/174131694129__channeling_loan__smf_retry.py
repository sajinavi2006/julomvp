# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2025-03-07 03:09
from __future__ import unicode_literals

from django.db import migrations

from juloserver.julo.models import FeatureSetting
from juloserver.channeling_loan.constants.constants import FeatureNameConst


def create_feature_settings_smf_channeling(apps, _schema_editor):
    FeatureSetting.objects.create(
        feature_name=FeatureNameConst.SMF_CHANNELING_RETRY,
        parameters={
            "max_retry_count": 2,
            "minutes": 120,
        },
        is_active=False,
        category="channeling_loan",
        description="SMF Channeling Loan Retry"
    )


class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.RunPython(create_feature_settings_smf_channeling, migrations.RunPython.noop),
    ]
