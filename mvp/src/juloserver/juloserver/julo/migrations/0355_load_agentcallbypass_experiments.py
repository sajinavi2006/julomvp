# -*- coding: utf-8 -*-
from __future__ import unicode_literals
from datetime import datetime, time
from dateutil.relativedelta import relativedelta
from django.db import migrations
from django.utils import timezone
from ..constants import ExperimentConst
from ..statuses import ApplicationStatusCodes


def load_agentcall_bypass_experiment_setting(apps, schema_editor):
    ExperimentSetting = apps.get_model("julo", "ExperimentSetting")
    today = timezone.now()
    start_date = today + relativedelta(day=27, hour=0, minute=0)
    end_date = today + relativedelta(day=9, month=3, hour=0, minute=0)
    experiments = [
        {
            "code": ExperimentConst.AGENT_CALL_BYPASS,
            "name": "Agent Call ByPass",
            "type": "payment",
            "schedule": "07:00",
            "action": None,
            "criteria": {
                "loan_id": "#last:1:6,7,8,9",
                "dpd": ["-5"],
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
        ('julo', '0354_partner_purchase_items'),
    ]

    operations = [
        migrations.RunPython(load_agentcall_bypass_experiment_setting, migrations.RunPython.noop)
    ]
