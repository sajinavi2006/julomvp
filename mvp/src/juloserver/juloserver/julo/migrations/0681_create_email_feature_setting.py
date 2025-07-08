# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import migrations
from ..constants import FeatureNameConst


def add_sent_email_and_tracking_feature(apps, schema_editor):
    FeatureSetting = apps.get_model("julo", "FeatureSetting")
    FeatureSetting.objects.get_or_create(is_active=True,
                                        feature_name=FeatureNameConst.SENT_EMAIl_AND_TRACKING,
                                        category="Streamlined Communication",
                                        parameters=None,
                                        description="auto call for 138 and auto change to 139 for call unanswered"
                                        )

class Migration(migrations.Migration):

    dependencies = [
        ('julo', '0680_add_field_to_email_history'),
    ]

    operations = [
        migrations.RunPython(add_sent_email_and_tracking_feature, migrations.RunPython.noop)
    ]