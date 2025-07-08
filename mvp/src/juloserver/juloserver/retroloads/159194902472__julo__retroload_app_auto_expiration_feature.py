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
    
    params = [
        {"origins" : [141, 172, 124],
         "destination": 139,
         "expiration_days" : 2
         },
        {"origins" : [162, 175],
         "destination": 143,
         "expiration_days": 5
         },
        {"origins": [138],
         "destination": 139,
         "expiration_days": 4
         }
    ]

    FeatureSetting.objects.get_or_create(is_active=True,
                                        feature_name=FeatureNameConst.APPLICATION_AUTO_EXPIRATION,
                                        category="Agent",
                                        parameters=params,
                                        description="auto expiration for several application status"
                                        )

class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.RunPython(add_predictive_missed_call_settings, migrations.RunPython.noop)
    ]
