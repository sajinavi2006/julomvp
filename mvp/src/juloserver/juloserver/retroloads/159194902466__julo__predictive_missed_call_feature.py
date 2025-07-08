# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import migrations, models
from django.utils import timezone
from juloserver.julo.statuses import ApplicationStatusCodes
from juloserver.julo.constants import FeatureNameConst
from juloserver.julo.constants import ExperimentConst
import django.contrib.postgres.fields.jsonb

from juloserver.julo.models import FeatureSetting


def add_predictive_missed_call_settings(apps, schema_editor):
    
    FeatureSetting.objects.get_or_create(is_active=True,
                                        feature_name=FeatureNameConst.PREDICTIVE_MISSED_CALL,
                                        category="Temporary",
                                        parameters={'is_running': False},
                                        description="predictive missed call for filter application"
                                        )

class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.RunPython(add_predictive_missed_call_settings, migrations.RunPython.noop)
    ]
