# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import migrations
from ..constants import FeatureNameConst


def update_pending_notification_feature_setting(apps, schema_editor):
    FeatureSetting = apps.get_model("julo", "FeatureSetting")
    featureSetting = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.PENDING_DISBURSEMENT_NOTIFICATION_MEMBER
        ).first()

    if featureSetting:
        isList = isinstance(featureSetting.parameters, list)
        parameters = {"users": [], "last_application_processed_date": None}

        if isList:
            parameters["users"] = featureSetting.parameters

        featureSetting.parameters = parameters
        featureSetting.save()


class Migration(migrations.Migration):

    dependencies = [
        ('julo', '0456_feature_setting_for_auto_disbursement_retry'),
    ]

    operations = [
        migrations.RunPython(update_pending_notification_feature_setting,
            migrations.RunPython.noop)
    ]
