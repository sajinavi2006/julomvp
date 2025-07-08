# -*- coding: utf-8 -*-
from __future__ import unicode_literals
from datetime import datetime, time
from dateutil.relativedelta import relativedelta
from django.db import migrations
from django.utils import timezone
from ..constants import ExperimentConst
from ..statuses import ApplicationStatusCodes


def load_robocall_experiment_setting(apps, schema_editor):
    ExperimentSetting = apps.get_model("julo", "ExperimentSetting")
    today = timezone.now()
    start_date = today + relativedelta(day=25, hour=0, minute=0)
    end_date = today + relativedelta(day=14, month=2, hour=0, minute=0)
    experiments = [
        {
            "code": ExperimentConst.UNSET_ROBOCALL,
            "name": "Not Set Active Robocall",
            "type": "payment",
            "schedule": "07:00",
            "action": None,
            "criteria": {
                "payment_id": "#last:2:61,62,63,64,65,66,67,68,69,70,71,72,73,74,75,76,77,78,79,80",
                "dpd":["-5", "-3"],
                "is_paid": False,
            },
            "start_date": datetime.combine(start_date, time.min),
            "end_date": datetime.combine(end_date, time.max),
            "is_active": True
        },
    ]


    for experiment in experiments:
        experiment_obj = ExperimentSetting(**experiment)
        experiment_obj.save()

class Migration(migrations.Migration):

    dependencies = [
        ('julo', '0341_auto_20190123_1142'),
    ]

    operations = [
        migrations.RunPython(load_robocall_experiment_setting, migrations.RunPython.noop)
    ]
