# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import migrations, models
from django.utils import timezone
from juloserver.julo.statuses import ApplicationStatusCodes
from juloserver.julo.constants import FeatureNameConst
from juloserver.julo.constants import ExperimentConst
import django.contrib.postgres.fields.jsonb

from juloserver.julo.models import FeatureSetting


def add_monty_sms_settings(apps, schema_editor):
    
    FeatureSetting.objects.get_or_create(is_active=True,
                                        feature_name=FeatureNameConst.MONTY_SMS,
                                        category="Messaging",
                                        description="set Monty as primary SMS client"
                                        )

class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.RunPython(add_monty_sms_settings, migrations.RunPython.noop)
    ]
