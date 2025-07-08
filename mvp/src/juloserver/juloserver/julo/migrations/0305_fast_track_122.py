# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import migrations, models
from django.utils import timezone
from ..statuses import ApplicationStatusCodes
from ..constants import FeatureNameConst
from ..constants import ExperimentConst
import django.contrib.postgres.fields.jsonb

def add_fast_track_122_experiment_settings(apps, schema_editor):
    FeatureSetting = apps.get_model("julo", "FeatureSetting")
    FeatureSetting.objects.get_or_create(is_active=False,
                                        feature_name=FeatureNameConst.BYPASS_FAST_TRACK_122,
                                        category="experiment",
                                        description="https://trello.com/c/KhBEkUoz"
                                        )

def add_experiments(apps, schema_editor):
    Experiment = apps.get_model("julo", "Experiment")
    experiments = [{
        "experiment": {
            "code": ExperimentConst.BYPASS_FT122,
            "name": "Bypass Fast Track 122",
            "status_old": ApplicationStatusCodes.SCRAPED_DATA_VERIFIED,
            "status_new": ApplicationStatusCodes.DOCUMENTS_VERIFIED,
            "date_start": timezone.now(),
            "date_end": timezone.now(),
            "is_active": False
        }
    }]
    for experiment in experiments:
        experiment_obj = Experiment(**experiment["experiment"])
        experiment_obj.save()


class Migration(migrations.Migration):

    dependencies = [
        ('julo', '0304_payment_ptp_robocall_phone_number'),
    ]

    operations = [
        migrations.RunPython(add_experiments, migrations.RunPython.noop),
        migrations.RunPython(add_fast_track_122_experiment_settings, migrations.RunPython.noop)
    ]