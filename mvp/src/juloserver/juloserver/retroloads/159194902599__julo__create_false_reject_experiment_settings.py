# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import migrations
from django.utils import timezone
from juloserver.julo.statuses import ApplicationStatusCodes
from datetime import datetime


from juloserver.julo.models import ExperimentTestGroup



from juloserver.julo.models import Experiment



def load_false_reject_minimization_experiment(apps, schema_editor):
    
    

    experiment = {
        "experiment": {
            "code": "FALSE_REJECT_MINIMIZATION",
            "name": "False Reject Minimization Experiment for the first timer customer",
            "status_old": 0,
            "status_new": 0,
            "date_start": datetime(2019, 12, 10),
            "date_end": datetime(2019, 12, 10),
            "is_active": True,
            "created_by": "Kumar"
        },
        "test_groups": [
            {
                "type": "application_xid",
                "value": "#nth:2:10,11,12,13,14,15,16,17,18,19,20,21,22,23,24",
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
    ]

    operations = [
        migrations.RunPython(load_false_reject_minimization_experiment, migrations.RunPython.noop)
    ]
