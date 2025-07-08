# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import migrations, models
from django.utils import timezone
from ..statuses import ApplicationStatusCodes
from ..constants import FeatureNameConst
from ..constants import ExperimentConst
import django.contrib.postgres.fields.jsonb

def add_predictive_missed_call_settings(apps, schema_editor):
    FeatureSetting = apps.get_model("julo", "FeatureSetting")
    FeatureSetting.objects.get_or_create(is_active=True,
                                        feature_name=FeatureNameConst.PREDICTIVE_MISSED_CALL,
                                        category="Temporary",
                                        parameters={'is_running': False},
                                        description="predictive missed call for filter application"
                                        )

class Migration(migrations.Migration):

    dependencies = [
        ('julo', '0332_add_172_to_feature_settings_autodialer_delay_revision'),
    ]

    operations = [
        migrations.RunPython(add_predictive_missed_call_settings, migrations.RunPython.noop)
    ]
