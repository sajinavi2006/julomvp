# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2025-03-03 03:58
from __future__ import unicode_literals

from django.db import migrations
from juloserver.julo.models import FeatureSetting
from juloserver.julo.constants import FeatureNameConst


def create_feature_setting_payback_listing(apps, _schema_editor):
    FeatureSetting.objects.create(
        feature_name=FeatureNameConst.REPAYMENT_PAYBACK_SERVICE_LIST,
        is_active=True,
        parameters={
            "include_list": [
                "autodebet",
                "OVO",
                "OVO_Tokenization",
                "cimb",
                "dana",
                "gopay_tokenization",
                "gopay",
                "bca",
                "oneklik",
                "gopay_autodebet",
                "DANA Biller",
                "faspay",
                "manual",
                "doku",
                "DANA_wallet",
                "cashback",
            ]
        },
        category='repayment',
        description="List of payback service allowed for payback listing",
    )


class Migration(migrations.Migration):

    dependencies = []

    operations = [
        migrations.RunPython(create_feature_setting_payback_listing, migrations.RunPython.noop),
    ]
