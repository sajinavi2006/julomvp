# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import migrations, models
from django.utils import timezone
from juloserver.julo.statuses import ApplicationStatusCodes
from juloserver.julo.constants import FeatureNameConst
from juloserver.julo.constants import ExperimentConst
import django.contrib.postgres.fields.jsonb

from juloserver.julo.models import FeatureSetting


def add_auto_call_ping_122_settings(apps, schema_editor):
    
    FeatureSetting.objects.get_or_create(is_active=False,
                                        feature_name=FeatureNameConst.AUTO_CALL_PING_122,
                                        category="Temporary",
                                        parameters={'is_running': False},
                                        description="auto call for 122 and auto change to 138 for call unanswered"
                                        )

class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.RunPython(add_auto_call_ping_122_settings, migrations.RunPython.noop)
    ]