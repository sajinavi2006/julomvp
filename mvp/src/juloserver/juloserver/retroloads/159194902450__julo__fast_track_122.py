# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import migrations, models
from django.utils import timezone
from juloserver.julo.statuses import ApplicationStatusCodes
from juloserver.julo.constants import FeatureNameConst
from juloserver.julo.constants import ExperimentConst
import django.contrib.postgres.fields.jsonb

from juloserver.julo.models import Experiment


from juloserver.julo.models import FeatureSetting


def add_fast_track_122_experiment_settings(apps, schema_editor):
    
    FeatureSetting.objects.get_or_create(is_active=False,
                                        feature_name=FeatureNameConst.BYPASS_FAST_TRACK_122,
                                        category="experiment",
                                        description="https://trello.com/c/KhBEkUoz"
                                        )

from juloserver.julo.models import Experiment


from juloserver.julo.models import FeatureSetting


def add_experiments(apps, schema_editor):
    
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
    ]

    operations = [
        migrations.RunPython(add_experiments, migrations.RunPython.noop),
        migrations.RunPython(add_fast_track_122_experiment_settings, migrations.RunPython.noop)
    ]