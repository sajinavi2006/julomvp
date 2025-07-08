# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import migrations
from django.utils import timezone
from ..statuses import ApplicationStatusCodes
from datetime import datetime


def load_fraud_model_experiment(apps, schema_editor):
    Experiment = apps.get_model("julo", "Experiment")

    experiment = {
        "experiment": {
            "code": "FRAUD_MODEL_105",
            "name": "Fraud Model Experiment",
            "status_old": 0,
            "status_new": 0,
            "date_start": datetime(2020, 1, 21),
            "date_end": datetime(2020, 2, 21),
            "is_active": True,
            "created_by": "Kumar"
        }
    }

    experiment_obj = Experiment(**experiment["experiment"])
    experiment_obj.save()


class Migration(migrations.Migration):
    dependencies = [
        ('julo', '0603_add_experiment_loan_generation_chunk'),
    ]

    operations = [
        migrations.RunPython(load_fraud_model_experiment, migrations.RunPython.noop)
    ]
