# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import migrations
from ..constants import FeatureNameConst


def add_pending_disbursement_notification_member_feature_settings(apps, schema_editor):
    FeatureSetting = apps.get_model("julo", "FeatureSetting")
    FeatureSetting.objects.get_or_create(is_active=True,
        feature_name=FeatureNameConst.PENDING_DISBURSEMENT_NOTIFICATION_MEMBER,
        category="disbursement",
        parameters=["UK2G42C1Z"],
        description="List User for Pending Disbursement Notification")


class Migration(migrations.Migration):

    dependencies = [
        ('julo', '0446_auto_20190613_1413'),
    ]

    operations = [
        migrations.RunPython(add_pending_disbursement_notification_member_feature_settings,
            migrations.RunPython.noop)
    ]
