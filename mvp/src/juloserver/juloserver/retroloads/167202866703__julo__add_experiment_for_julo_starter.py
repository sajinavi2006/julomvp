# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2022-12-26 04:24
from __future__ import unicode_literals

from django.db import migrations
from django.utils import timezone

from juloserver.julo.constants import ExperimentConst
from juloserver.julo.models import ExperimentSetting


def add_new_experiment_for_julo_starter(apps, schema_editor):
    """
    Detail can be following this card:
    https://juloprojects.atlassian.net/browse/RUS1-1529
    """

    is_exist = ExperimentSetting.objects.filter(code=ExperimentConst.JULO_STARTER_EXPERIMENT).exists()
    if not is_exist:
        ExperimentSetting.objects.create(
            code=ExperimentConst.JULO_STARTER_EXPERIMENT,
            name="Julo Starter Experiment",
            is_active=False,
            is_permanent=False,
            start_date=timezone.localtime(timezone.now()),
            end_date=timezone.localtime(timezone.now()),
            criteria={
                "regular_customer_id": [2, 3, 4, 5, 6, 7, 8, 9],
                "julo_starter_customer_id": [0, 1],
                "target_version": "==7.9.0"
            },
            type="application",
        )


class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.RunPython(add_new_experiment_for_julo_starter, migrations.RunPython.noop)
    ]
