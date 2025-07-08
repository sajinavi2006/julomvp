# -*- coding: utf-8 -*-
from __future__ import unicode_literals
from dateutil.relativedelta import relativedelta
from django.db import migrations
from django.utils import timezone
from ..statuses import ApplicationStatusCodes


def load_payment_january_lottery_experiments(apps, schema_editor):
    ExperimentSetting = apps.get_model("julo", "ExperimentSetting")
    today = timezone.now()
    end_date = today 

    experiments = [
        {
            "code": "LOTTERYCASHSPAM",
            "name": "January Lottery for payment cash spam",
            "type": "payment",
            "schedule": "09:00",
            "action": "send_lottery_cash",
            "criteria": {
                "payment_id": "#last:2:01,02,03,04,05,06,07,08,09,10,11,12,13,14,15",
                "dpd":["-6", "-4", "-2"],
                "payment_number": "gt:duration:2",
                "is_paid": False,
            },
            "start_date": today + relativedelta(day=22, hour=0, minute=0),
            "end_date": today + relativedelta(day=10, month=2, hour=0, minute=0),
            "is_active": True
        },
        {
            "code": "LOTTERYCASH",
            "name": "January Lottery for payment cash no spam",
            "type": "payment",
            "schedule": "09:00",
            "action": "send_lottery_cash",
            "criteria": {
                "payment_id": "#last:2:16,17,18,19,20,21,22,23,24,25,26,27,28,29,30",
                "dpd":["-5"],
                "payment_number": "gt:duration:2",
                "is_paid": False,
            },
            "start_date": today + relativedelta(day=22, hour=0, minute=0),
            "end_date": today + relativedelta(day=10, month=2, hour=0, minute=0),
            "is_active": True
        },
        {
            "code": "LOTTERYPHONESPAM",
            "name": "January Lottery for payment lottery spam",
            "type": "payment",
            "schedule": "09:00",
            "action": "send_lottery_phone",
            "criteria": {
                "payment_id": "#last:2:31,32,33,34,35,36,37,38,39,40,41,42,43,44,45",
                "dpd":["-6", "-4", "-2"],
                "payment_number": "gt:duration:2",
                "is_paid": False,
            },
            "start_date": today + relativedelta(day=22, hour=0, minute=0),
            "end_date": today + relativedelta(day=10, month=2, hour=0, minute=0),
            "is_active": True
        },
        {
            "code": "LOTTERYPHONE",
            "name": "January Lottery for payment lottery no spam",
            "type": "payment",
            "schedule": "09:00",
            "action": "send_lottery_phone",
            "criteria": {
                "payment_id": "#last:2:46,47,48,49,50,51,52,53,54,55,56,57,58,59,60",
                "dpd":["-5"],
                "payment_number": "gt:duration:2",
                "is_paid": False,
            },
            "start_date": today + relativedelta(day=22, hour=0, minute=0),
            "end_date": today + relativedelta(day=10, month=2, hour=0, minute=0),
            "is_active": True
        }
    ]


    for experiment in experiments:
        experiment_obj = ExperimentSetting(**experiment)
        experiment_obj.save()

class Migration(migrations.Migration):

    dependencies = [
        ('julo', '0337_experimentsetting_paymentexperiment'),
    ]

    operations = [
        migrations.RunPython(load_payment_january_lottery_experiments, migrations.RunPython.noop)
    ]