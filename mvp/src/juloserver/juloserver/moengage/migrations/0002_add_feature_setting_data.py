# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import migrations
from juloserver.julo.constants import FeatureNameConst


def add_moengage_max_event_upload_rule(apps, _schema_editor):
    FeatureSetting = apps.get_model("julo", "FeatureSetting")
    FeatureSetting.objects.get_or_create(
        is_active=True,
        feature_name=FeatureNameConst.MOENGAGE_EVENT,
        category="moengage",
        parameters={'loan_status_reminder_max_event': 20,
                    'loan_payment_reminder_max_event': 20,
                    'hi_season_reminder_max_event': 20,
                    'payment_reminder_max_event': 20},
        description="Config for moengage event maximum upload data"
    )


class Migration(migrations.Migration):

    dependencies = [
        ('moengage', '0001_initial'),
    ]

    operations = [
        migrations.RunPython(add_moengage_max_event_upload_rule, migrations.RunPython.noop)
    ]
