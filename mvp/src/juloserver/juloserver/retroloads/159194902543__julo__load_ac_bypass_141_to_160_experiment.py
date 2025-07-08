# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import migrations
from django.utils import timezone
from juloserver.julo.statuses import ApplicationStatusCodes


from juloserver.julo.models import ExperimentTestGroup



from juloserver.julo.models import Experiment



def load_AC_bypass_141_TO_160_experiment(apps, schema_editor):
    
    

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
    ]

    operations = [
        migrations.RunPython(load_AC_bypass_141_TO_160_experiment, migrations.RunPython.noop)
    ]