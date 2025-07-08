# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import migrations
from django.utils import timezone
from juloserver.julo.statuses import ApplicationStatusCodes


from juloserver.julo.models import ExperimentAction



from juloserver.julo.models import ExperimentTestGroup



from juloserver.julo.models import Experiment



def load_PVA_bypass_experiment(apps, schema_editor):
    
    
    

    experiment = {
        "experiment": {
            "code": "BypassPVA124",
            "name": "Bypass PVA 124 to 130",
            "status_old": ApplicationStatusCodes.DOCUMENTS_VERIFIED,
            "status_new": ApplicationStatusCodes.VERIFICATION_CALLS_SUCCESSFUL,
            "date_start": timezone.now(),
            "date_end": timezone.now(),
            "is_active": False
        },
        "test_groups": [
            {
                "type": "application_id",
                "value": "#nth:-1:5,6,7,8,9",
            }
        ],
        "actions": [
            {
                "type": "CHANGE_STATUS",
                "value": ApplicationStatusCodes.APPLICANT_CALLS_SUCCESSFUL,
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
    ]

    operations = [
        migrations.RunPython(load_PVA_bypass_experiment, migrations.RunPython.noop)
    ]