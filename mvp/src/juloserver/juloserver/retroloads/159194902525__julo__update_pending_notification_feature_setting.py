# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import migrations
from juloserver.julo.constants import FeatureNameConst


from juloserver.julo.models import FeatureSetting



def update_pending_notification_feature_setting(apps, schema_editor):
    
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
    ]

    operations = [
        migrations.RunPython(update_pending_notification_feature_setting,
            migrations.RunPython.noop)
    ]
