# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import migrations
from juloserver.julo.constants import ExperimentConst

from juloserver.julo.models import ExperimentSetting


def update_pn_experiment(apps, schema_editor):
    
    pn_experiment = ExperimentSetting.objects.filter(code=ExperimentConst.PN_SCRIPT_EXPERIMENT)
    pn_experiment.update(
        criteria={
            "dpd": [-5, -4, -3, -2, -1, 0],
            "test_group": [4, 5, 6, 7, 8, 9],
            "start_due_date": "2020-01-27",
            "end_due_date": "2020-02-10",
        },
        start_date="2020-01-21 00:00:00+00",
        end_date="2020-02-10 00:00:00+00",
        is_active=True
    )


class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.RunPython(update_pn_experiment,
            migrations.RunPython.noop)
    ]