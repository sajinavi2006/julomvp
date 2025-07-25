# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2023-11-19 16:07
from __future__ import unicode_literals

from dateutil.relativedelta import relativedelta

from django.db import migrations
from django.utils import timezone

from juloserver.julo.models import ExperimentSetting
from juloserver.julo.constants import ExperimentConst


def update_experiment_setting_leverage_bank_statement(apps, schema_editor):
    setting = ExperimentSetting.objects.get_or_none(
    	code=ExperimentConst.LEVERAGE_BANK_STATEMENT_EXPERIMENT
    )

    if setting:
	    setting.update_safely(
	        criteria={
	            "credit_limit_constant": 1.5,
	            "credit_limit_threshold": 300000,
	            "max_limit": 5000000,
	            "a/b_test": {
	                "per_request": 2,
	                "percentage": 50,
	            },
	            "clients": {
                	"right": "perfios",
                	"left": "powercred",
                },
	        }
	    )


class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.RunPython(update_experiment_setting_leverage_bank_statement, migrations.RunPython.noop)
    ]
