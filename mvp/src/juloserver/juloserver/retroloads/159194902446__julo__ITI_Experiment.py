# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import migrations, models
from django.utils import timezone
from juloserver.julo.statuses import ApplicationStatusCodes
from juloserver.julo.constants import FeatureNameConst
import django.contrib.postgres.fields.jsonb

from juloserver.julo.models import StatusLookup


from juloserver.julo.models import ExperimentAction


from juloserver.julo.models import ExperimentTestGroup


from juloserver.julo.models import Experiment


from juloserver.julo.models import FeatureSetting


def add_iti_experiment_settings(apps, schema_editor):
    
    FeatureSetting.objects.get_or_create(is_active=False,
                                        feature_name=FeatureNameConst.BYPASS_ITI_EXPERIMENT_122,
                                        category="experiment",
                                        description="https://trello.com/c/ehPbMXuQ"
                                        )
    FeatureSetting.objects.get_or_create(is_active=False,
                                        feature_name=FeatureNameConst.BYPASS_ITI_EXPERIMENT_125,
                                        category="experiment",
                                        description="https://trello.com/c/ehPbMXuQ"
                                        )

from juloserver.julo.models import StatusLookup


from juloserver.julo.models import ExperimentAction


from juloserver.julo.models import ExperimentTestGroup


from juloserver.julo.models import Experiment


from juloserver.julo.models import FeatureSetting


def add_experiments(apps, schema_editor):
    
    
    
    
    experiments = [{
        "experiment": {
            "code": "BypassITI122",
            "name": "Bypass ITI 122",
            "status_old": ApplicationStatusCodes.SCRAPED_DATA_VERIFIED,
            "status_new": ApplicationStatusCodes.DOCUMENTS_VERIFIED,
            "date_start": timezone.now(),
            "date_end": timezone.now(),
            "is_active": False
        },
        "test_groups": [
            {
                "type": "application_xid",
                "value": "#nth:-1:1,2,3",
            },
            {
                "type": "product",
                "value": "mtl1,stl1,mtl2,stl2"
            },
        ],
        "actions": [
            {
                "type": "ADD_NOTE",
                "value": "Bypass ITI 122",
            },
        ]
    },
    {
        "experiment": {
            "code": "BypassITI125",
            "name": "Bypass ITI 125",
            "status_old": ApplicationStatusCodes.PRE_REJECTION,
            "status_new": ApplicationStatusCodes.CALL_ASSESSMENT,
            "date_start": timezone.now(),
            "date_end": timezone.now(),
            "is_active": False
        },
        "test_groups": [
            {
                "type": "application_xid",
                "value": "#nth:-1:1,2,3",
            },
            {
                "type": "product",
                "value": "mtl1,stl1,mtl2,stl2"
            },
        ],
        "actions": [
            {
                "type": "ADD_NOTE",
                "value": "Bypass ITI 125",
            },
        ]
    }]

    for experiment in experiments:
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

from juloserver.julo.models import StatusLookup


from juloserver.julo.models import ExperimentAction


from juloserver.julo.models import ExperimentTestGroup


from juloserver.julo.models import Experiment


from juloserver.julo.models import FeatureSetting


def add_handler_125(apps, schema_editor):
    
    status_lookup, created = StatusLookup.objects.get_or_create(status_code=ApplicationStatusCodes.CALL_ASSESSMENT)
    status_lookup.handler = 'Status125Handler'
    status_lookup.save()

class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.RunPython(add_experiments, migrations.RunPython.noop),
        migrations.RunPython(add_handler_125, migrations.RunPython.noop),
        migrations.RunPython(add_iti_experiment_settings, migrations.RunPython.noop)
    ]