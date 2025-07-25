# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2021-04-26 07:17
from __future__ import unicode_literals
from builtins import object
from builtins import range
from django.db import migrations
from juloserver.julo.models import FeatureSetting
from juloserver.account_payment.constants import AccountPaymentCons


def add_feature_setting_to_store_list_dpd(apps, schema_editor):
    list_of_dpds = list(range(-7, 16))
    other_dpd = [21, 30, 60]
    list_of_dpds.extend(other_dpd)

    dpds_to_snapshot = {
        'dpds_to_snapshot': list_of_dpds
    }

    FeatureSetting.objects.create(
        feature_name=AccountPaymentCons.ACCOUNT_PAYMENT,
        parameters=dpds_to_snapshot,
        is_active=True,
        description='store list of dpd',
        category='payment reminder'
    )


class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
         migrations.RunPython(
            add_feature_setting_to_store_list_dpd, migrations.RunPython.noop),
    ]
