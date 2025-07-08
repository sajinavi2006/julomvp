# -*- coding: utf-8 -*-
from __future__ import unicode_literals
from datetime import datetime, time
from dateutil.relativedelta import relativedelta
from django.db import migrations
from django.utils import timezone

from juloserver.cootek.constants import DpdConditionChoices, CriteriaChoices
from juloserver.cootek.models import CootekRobot, CootekConfiguration
from juloserver.julo.constants import ExperimentConst
from juloserver.julo.statuses import ApplicationStatusCodes

from juloserver.julo.models import ExperimentSetting


def load_cootek_late_dpd_j1_experiment_setting(apps, schema_editor):
    experiment = {
            "code": ExperimentConst.COOTEK_LATE_DPD_J1,
            "name": "Cootek Late DPD J1",
            "type": "collection",
            "schedule": "11:50",
            "action": None,
            "criteria": {
                "account_id": "#last:1:0,1,2,3,4,5",
            },
            "start_date": "2021-06-21 00:00:00+00",
            "end_date": "2021-07-05 00:00:00+00",
            "is_active": True
        }

    ExperimentSetting.objects.create(**experiment)
    # setup cootek configuration
    cootek_configs = [
        # dpd 1 - 4
        {
            'strategy_name': 'EXPERIMENT_DPD_LATE_1_4',
            'time_to_start': '12:00:00',
            'task_type': 'EXPERIMENT_DPD_LATE_1-4',
            'repeat_number': 3, 'called_at': 1, 'called_to': 4,
            'is_active': True, 'dpd_condition': DpdConditionChoices.RANGE,
            'criteria': CriteriaChoices.LATE_DPD_EXPERIMENT,
            'robot_identifier': '93d182db770b381152f5fa5ccd2a519a',
            'robot_name': "robot_experiment_late_dpd_1-4",
        },
        # dpd 5 - 40
        {
            'strategy_name': 'EXPERIMENT_DPD_LATE_5_40',
            'time_to_start': '12:00:00',
            'task_type': 'EXPERIMENT_DPD_LATE_5-40',
            'repeat_number': 3, 'called_at': 5, 'called_to': 40,
            'is_active': True, 'dpd_condition': DpdConditionChoices.RANGE,
            'criteria': CriteriaChoices.LATE_DPD_EXPERIMENT,
            'robot_identifier': '92ee3c2eebbe6c4d3bc3d9110bd448b6',
            'robot_name': "robot_experiment_late_dpd_5-40",
        },
    ]

    for config in cootek_configs:
        robot = CootekRobot.objects.filter(
            robot_identifier=config['robot_identifier']).first()
        if not robot:
            robot = CootekRobot.objects.create(
                robot_identifier=config['robot_identifier'],
                robot_name=config['robot_name'],
                is_group_method=True
            )

        CootekConfiguration.objects.create(
            is_active=config.get('is_active', True),
            time_to_start=config['time_to_start'],
            strategy_name=config['strategy_name'],
            task_type=config['task_type'],
            called_at=config['called_at'],
            called_to=config['called_to'],
            number_of_attempts=config['repeat_number'],
            dpd_condition=config['dpd_condition'],
            criteria=config['criteria'],
            cootek_robot=robot,
            time_to_prepare='11:50:00',
            exclude_risky_customer=config.get('risky_customer', False),
            from_previous_cootek_result=False,
        )


class Migration(migrations.Migration):
    dependencies = [
    ]

    operations = [
        migrations.RunPython(load_cootek_late_dpd_j1_experiment_setting, migrations.RunPython.noop)
    ]
