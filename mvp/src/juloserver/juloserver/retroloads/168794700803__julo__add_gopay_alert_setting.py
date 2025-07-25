# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2023-06-28 10:10
from __future__ import unicode_literals

from django.db import migrations

from juloserver.disbursement.constants import GopayAlertDefault
from juloserver.julo.constants import FeatureNameConst
from juloserver.julo.models import FeatureSetting


def create_gopay_alert_setting(apps, _schema_editor):
    parameters = {
        'threshold': GopayAlertDefault.THRESHOLD,
        'message': 'Gopay available balance {current_balance} is less then threshold {threshold}. '
                   '<@U02B843J7V0> , <@U04H63S2XC7>, <@U05FA927QAY>, <@UH5H7PNE6> please top up!',
        'channel': GopayAlertDefault.CHANNEL
    }

    FeatureSetting.objects.create(
        feature_name=FeatureNameConst.GOPAY_BALANCE_ALERT,
        is_active=True,
        parameters=parameters,
        category='gopay',
        description='Default - Channel: #partner_balance - Threshold: 30mil - '
                    'Message: <!here> Gopay available balance is less then threshold. '
                    'Please top up!'
    )


class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.RunPython(create_gopay_alert_setting, migrations.RunPython.noop),
    ]
