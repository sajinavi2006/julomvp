# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import migrations
from juloserver.julo.constants import FeatureNameConst


def add_notification_balance_amount_feature_settings(apps, schema_editor):
    FeatureSetting = apps.get_model("julo", "FeatureSetting")
    FeatureSetting.objects.get_or_create(is_active=True,
        feature_name=FeatureNameConst.NOTIFICATION_BALANCE_AMOUNT,
        category="disbursement",
        parameters= {
            "users": ["UJGLJ25L2", "UBV0WQ0AE", "U7B66LMC1", "UH85AL05P"],
            "balance_threshold": 200000000
        },
        description="BCA and Xfers Low Balance Notification")


class Migration(migrations.Migration):

    dependencies = [
        ('julo', '0463_seed_default_data_to_bank_table'),
    ]

    operations = [
        migrations.RunPython(add_notification_balance_amount_feature_settings,
            migrations.RunPython.noop)
    ]
