# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import migrations, models
from django.utils import timezone
from ..statuses import ApplicationStatusCodes
from ..constants import FeatureNameConst
from ..constants import ExperimentConst
import django.contrib.postgres.fields.jsonb

def add_monty_sms_settings(apps, schema_editor):
    FeatureSetting = apps.get_model("julo", "FeatureSetting")
    FeatureSetting.objects.get_or_create(is_active=True,
                                        feature_name=FeatureNameConst.MONTY_SMS,
                                        category="Messaging",
                                        description="set Monty as primary SMS client"
                                        )

class Migration(migrations.Migration):

    dependencies = [
        ('julo', '0430_PTP_amount'),
    ]

    operations = [
        migrations.RunPython(add_monty_sms_settings, migrations.RunPython.noop)
    ]
