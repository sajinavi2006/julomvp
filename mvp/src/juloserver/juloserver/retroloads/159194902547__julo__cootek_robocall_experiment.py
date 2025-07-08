# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import migrations
from juloserver.julo.constants import ExperimentConst


from juloserver.julo.models import ExperimentSetting



def add_experiment_setting_cootek_robocall_experiment(apps, schema_editor):
    
    ExperimentSetting.objects.get_or_create(is_active=True,
        code=ExperimentConst.COOTEK_AI_ROBOCALL_TRIAL,
        name="Cootek AI Robocall trial v2",
        start_date="2019-08-26 00:00:00+00",
        end_date="2019-09-07 00:00:00+00",
        schedule="",
        action="",
        type="payment",
        criteria={"dpd": [-1, 0], "loan_id": "#last:1:4,5,6"})


class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.RunPython(add_experiment_setting_cootek_robocall_experiment,
            migrations.RunPython.noop)
    ]
