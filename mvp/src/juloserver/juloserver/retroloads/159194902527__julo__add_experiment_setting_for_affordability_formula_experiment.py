# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import migrations
from juloserver.julo.constants import FeatureNameConst


from juloserver.julo.models import ExperimentSetting



def add_experiment_setting_for_affordability_formula_experiment(apps, schema_editor):
    
    ExperimentSetting.objects.get_or_create(is_active=True,
        code="AffordabilityFormulaExperiment",
        name="Affordability Formula Experiment",
        start_date="2019-07-19 00:00:00+00",
        end_date="2019-08-19 00:00:00+00",
        schedule="",
        action="",
        type="formula",
        criteria="{}")


class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.RunPython(add_experiment_setting_for_affordability_formula_experiment,
            migrations.RunPython.noop)
    ]
