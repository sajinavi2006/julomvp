# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import migrations
from django.utils import timezone
from ..statuses import ApplicationStatusCodes


def load_BCC_experiments(apps, schema_editor):
    Experiment = apps.get_model("julo", "Experiment")
    ExperimentTestGroup = apps.get_model("julo", "ExperimentTestGroup")
    ExperimentAction = apps.get_model("julo", "ExperimentAction")
    
    experiment = {
        "experiment": {
            "code": "ABCC",
            "name": "Bypass CA Calculation",
            "status_old": ApplicationStatusCodes.VERIFICATION_CALLS_SUCCESSFUL,
            "status_new": ApplicationStatusCodes.APPLICANT_CALLS_SUCCESSFUL,
            "date_start": timezone.now(),
            "date_end": timezone.now(),
            "is_active": False
        },
        "test_groups": [
            {
                "type": "application_id",
                "value": "#nth:-1:1,2,3,4,5",
            },
            {
                "type": "product",
                "value": "mtl1,stl1,mtl2,stl2"
            },
        ],
        "actions": [
            {
                "type": "CHANGE_STATUS",
                "value": ApplicationStatusCodes.OFFER_ACCEPTED_BY_CUSTOMER,
            },
        ]
    }

    experiment_obj = Experiment(**experiment["experiment"])
    experiment_obj.save()
    for test_group in experiment["test_groups"]:
        test_group['experiment'] = experiment_obj
        experiment_test_group_obj = ExperimentTestGroup(**test_group)
        experiment_test_group_obj.save()
    for action in experiment["actions"]:
        action['experiment'] = experiment_obj
        experiment_action_obj = ExperimentAction(**action)
        experiment_action_obj.save()


class Migration(migrations.Migration):

    dependencies = [
        ('julo', '0269_load_ITIFTC_Experiments'),
    ]

    operations = [
        migrations.RunPython(load_BCC_experiments, migrations.RunPython.noop)
    ]