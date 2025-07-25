# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2024-04-08 06:30
from __future__ import unicode_literals

from django.db import migrations
from juloserver.julo.models import FeatureSetting
from juloserver.channeling_loan.constants import (
    FeatureNameConst,
    ChannelingConst,
)


def update_risk_premium_on_channeling_loan_config(apps, _schema_editor):
    fs = FeatureSetting.objects.filter(feature_name=FeatureNameConst.CHANNELING_LOAN_CONFIG).last()
    if fs:
        # INCLUDE_LOAN_ADJUSTED will include loan even if its adjusted
        # as long the channeling daily interest is smaller than our current daily interest
        parameters = fs.parameters
        for key in parameters.keys():
            parameters[key]['rac']['INCLUDE_LOAN_ADJUSTED'] = False
            if key == ChannelingConst.BSS:
                parameters[key]['rac']['INCLUDE_LOAN_ADJUSTED'] = True

        fs.parameters = parameters
        fs.save()


class Migration(migrations.Migration):

    dependencies = []

    operations = [
        migrations.RunPython(
            update_risk_premium_on_channeling_loan_config, migrations.RunPython.noop
        ),
    ]
