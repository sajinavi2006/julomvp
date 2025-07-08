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
        parameters = {
            "users": featureSetting.parameters['users'],
            "last_application_170_processed_date":
                featureSetting.parameters['last_application_processed_date'],
            "last_application_181_processed_date":
                featureSetting.parameters['last_application_processed_date'],
        }

        if isList:
            parameters["users"] = []
            parameters["last_application_170_processed_date"] = None
            parameters["last_application_181_processed_date"] = None


        featureSetting.parameters = parameters
        featureSetting.save()


class Migration(migrations.Migration):

    dependencies = [
        ('julo', '0464_notification_balance_amount'),
    ]

    operations = [
        migrations.RunPython(update_pending_notification_feature_setting,
            migrations.RunPython.noop)
    ]
