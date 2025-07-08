# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import migrations
from django.utils import timezone
from ..statuses import ApplicationStatusCodes


def load_AC_bypass_141_TO_160_experiment(apps, schema_editor):
    Experiment = apps.get_model("julo", "Experiment")
    ExperimentTestGroup = apps.get_model("julo", "ExperimentTestGroup")

    experiment = {
        "experiment": {
            "code": "ACBypass141",
            "name": "Activation Call bypass 141 to 160 for frist time customer and non ITI",
            "status_old": ApplicationStatusCodes.OFFER_ACCEPTED_BY_CUSTOMER,
            "status_new": ApplicationStatusCodes.ACTIVATION_CALL_SUCCESSFUL,
            "date_start": timezone.now(),
            "date_end": timezone.now(),
            "is_active": True
        },
        "test_groups": [
            {
                "type": "application_id",
                "value": "#nth:-1:1,2,3,4,5,6,7",
            }
        ]
    }

    experiment_obj = Experiment(**experiment["experiment"])
    experiment_obj.save()
    for test_group in experiment["test_groups"]: 
        test_group['experiment'] = experiment_obj
        experiment_test_group_obj = ExperimentTestGroup(**test_group)
        experiment_test_group_obj.save()


class Migration(migrations.Migration):
    dependencies = [
        ('julo', '0474_alter_sequence_payback_transaction_table'),
    ]

    operations = [
        migrations.RunPython(load_AC_bypass_141_TO_160_experiment, migrations.RunPython.noop)
    ]