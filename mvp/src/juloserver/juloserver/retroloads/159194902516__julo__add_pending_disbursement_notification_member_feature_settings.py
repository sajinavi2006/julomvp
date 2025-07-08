# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import migrations
from juloserver.julo.constants import FeatureNameConst


from juloserver.julo.models import FeatureSetting



def add_pending_disbursement_notification_member_feature_settings(apps, schema_editor):
    
    FeatureSetting.objects.get_or_create(is_active=True,
        feature_name=FeatureNameConst.PENDING_DISBURSEMENT_NOTIFICATION_MEMBER,
        category="disbursement",
        parameters=["UK2G42C1Z"],
        description="List User for Pending Disbursement Notification")


class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.RunPython(add_pending_disbursement_notification_member_feature_settings,
            migrations.RunPython.noop)
    ]
