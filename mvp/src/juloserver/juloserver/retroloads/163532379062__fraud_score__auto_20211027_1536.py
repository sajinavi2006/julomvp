# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2021-08-08 19:57
from __future__ import unicode_literals
from juloserver.julo.constants import ExperimentConst
from django.utils import timezone
from dateutil.relativedelta import relativedelta

from django.db import migrations


def update_bonza_reverse_experiment_feature_for_enhancements(apps, schema_editor):
    ExperimentSetting = apps.get_model("julo", "ExperimentSetting")
    experiement = ExperimentSetting.objects.filter(
        name="Bonza Reverse Experiment").last()
    if not experiement:
        return
    criteria = experiement.criteria
    criteria['control_performance_grp_digit_list'] = [0, 1, 2, 3, 4]
    experiement.criteria = criteria
    experiement.save()


class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.RunPython(
            update_bonza_reverse_experiment_feature_for_enhancements, migrations.RunPython.noop)
    ]
