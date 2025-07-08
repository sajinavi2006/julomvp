# -*- coding: utf-8 -*-
from __future__ import unicode_literals
import datetime
from django.db import migrations
from django.utils.timezone import utc
from juloserver.julo.constants import ExperimentConst

from juloserver.julo.models import ExperimentSetting


def active_robocall_experiment_setting_aug_peak(apps, schema_editor):
    
    experiment_setting = ExperimentSetting.objects.get(code=ExperimentConst.ROBOCALL_SCRIPT)
    if experiment_setting:
        start_date = datetime.datetime(2019, 8, 22, 0, 0, 0, 0, tzinfo=utc)
        end_date = datetime.datetime(2019, 9, 5, 0, 0, 0, 0, tzinfo=utc)
        new_criteria = {"dpd": ["-5", "-3"], "is_paid": False, "loan_id": "#last:1:7,8,9"}
        experiment_setting.criteria = new_criteria
        experiment_setting.start_date = start_date
        experiment_setting.end_date = end_date
        experiment_setting.save()


class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.RunPython(active_robocall_experiment_setting_aug_peak,
            migrations.RunPython.noop)
    ]
