# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import migrations
from django.utils import timezone
from datetime import datetime


from juloserver.julo.models import Experiment



def create_experiment_remove_own_phone(apps, schema_editor):
    

    experiment = {
        "experiment": {
            "code": "Is_Own_Phone_Experiment",
            "name": "Remove Binary Check for is_own_phone",
            "status_old": 0,
            "status_new": 0,
            "date_start": datetime(2020, 1, 23),
            "date_end": datetime(2020, 3, 23),
            "is_active": True,
            "created_by": "Kumar"
        }
    }

    experiment_obj = Experiment(**experiment["experiment"])
    experiment_obj.save()


class Migration(migrations.Migration):
    dependencies = [
    ]

    operations = [
        migrations.RunPython(create_experiment_remove_own_phone, migrations.RunPython.noop)
    ]
