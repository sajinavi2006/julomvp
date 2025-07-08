# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import migrations
from django.utils import timezone
from juloserver.julo.statuses import ApplicationStatusCodes


from juloserver.julo.models import ExperimentAction



from juloserver.julo.models import ExperimentTestGroup



from juloserver.julo.models import Experiment



def load_ITIFTC_experiments(apps, schema_editor):
    
    
    
    
    experiments = [
        {
            "code": "ITIFTC121",
            "name": "Index Trust Income First Time Customer Experiment",
            "status_old": ApplicationStatusCodes.SCRAPED_DATA_VERIFIED,
            "status_new": ApplicationStatusCodes.DOCUMENTS_VERIFIED,
            "date_start": timezone.now(),
            "date_end": timezone.now(),
            "is_active": False
        },
        {
            "code": "ITIFTC132",
            "name": "Index Trust Income First Time Customer Experiment",
            "status_old": ApplicationStatusCodes.APPLICATION_RESUBMITTED,
            "status_new": ApplicationStatusCodes.DOCUMENTS_VERIFIED,
            "date_start": timezone.now(),
            "date_end": timezone.now(),
            "is_active": False
        }
    ]

    experiment_test_groups = [
        {
            "type": "application_id",
            "value": "#nth:-1:1,2,3,4", 
        },
        {
            "type": "loan_count",
            "value": "#eq:0"
        }
    ]

    experiment_action = {
        "type": "CHANGE_STATUS",
        "value": ApplicationStatusCodes.VERIFICATION_CALLS_SUCCESSFUL
    }

    for experiment in experiments:
        experiment_obj = Experiment(**experiment)
        experiment_obj.save()
        for experiment_test_group in experiment_test_groups:
            experiment_test_group['experiment'] = experiment_obj
            experiment_test_group_obj = ExperimentTestGroup(**experiment_test_group)
            experiment_test_group_obj.save()
        experiment_action['experiment'] = experiment_obj
        experiment_action_obj = ExperimentAction(**experiment_action)
        experiment_action_obj.save()

class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.RunPython(load_ITIFTC_experiments, migrations.RunPython.noop)
    ]