# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import migrations
from juloserver.julo.constants import ExperimentConst


from juloserver.julo.models import ExperimentSetting



def add_experiment_setting_pn_script(apps, schema_editor):
    
    ExperimentSetting.objects.get_or_create(is_active=True,
                                            code=ExperimentConst.PN_SCRIPT_EXPERIMENT,
                                            name="PN Script Experiment",
                                            start_date="2019-09-22 00:00:00+00",
                                            end_date="2019-10-10 00:00:00+00",
                                            schedule="",
                                            action="",
                                            type="notification",
                                            criteria={
                                                "dpd": [-5, -4, -3, -2, -1, 0],
                                                "test_group_1": [2, 3, 4, 5],
                                                "test_group_2": [6, 7, 8, 9],
                                                "start_due_date": "2019-09-27",
                                                "end_due_date": "2019-10-10",
                                            }
                                            )


class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.RunPython(add_experiment_setting_pn_script,
            migrations.RunPython.noop)
    ]
