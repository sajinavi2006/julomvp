# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2024-06-11 03:51
from __future__ import unicode_literals

from django.db import migrations


def create_feature_settings_credgenics_repayment_exclusion(app, __schema_editor):
    from juloserver.julo.models import FeatureSetting
    from juloserver.julo.constants import FeatureNameConst

    feature_setting = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.CREDGENICS_REPAYMENT
    ).exists()

    if not feature_setting:
        FeatureSetting.objects.create(
            feature_name=FeatureNameConst.CREDGENICS_REPAYMENT,
            is_active=False,
            category='credgenics',
            description='Credgenics Repayment feature setting',
            parameters={'include_batch': [1]},
        )


class Migration(migrations.Migration):

    dependencies = []

    operations = [
        migrations.RunPython(
            create_feature_settings_credgenics_repayment_exclusion, migrations.RunPython.noop
        ),
    ]
