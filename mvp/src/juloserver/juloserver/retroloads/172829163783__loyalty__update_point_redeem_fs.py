# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2024-10-07 09:00
from __future__ import unicode_literals

from django.db import migrations

from juloserver.loyalty.constants import FeatureNameConst
from juloserver.julo.models import FeatureSetting


def update_point_redeem_feature_setting(apps, _schema_editor):
    fs = FeatureSetting.objects.get(feature_name=FeatureNameConst.POINT_REDEEM)
    parameters = fs.parameters
    parameters['dana_transfer'].pop("admin_fee", None)
    parameters['gopay_transfer'].pop("admin_fee", None)
    parameters['dana_transfer']["julo_fee"] = 0
    parameters['gopay_transfer'].update({
        "partner_fee": 1000,
        "julo_fee": 0,
    })
    fs.parameters = parameters
    fs.save()


class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [migrations.RunPython(update_point_redeem_feature_setting, migrations.RunPython.noop)]
