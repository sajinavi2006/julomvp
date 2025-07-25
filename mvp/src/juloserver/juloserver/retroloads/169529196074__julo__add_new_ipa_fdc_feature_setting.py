# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2023-09-21 10:26
from __future__ import unicode_literals

from django.db import migrations
from django.utils import timezone

from juloserver.julo.constants import ExperimentConst
from juloserver.julo.models import ExperimentSetting


def add_new_experiment_for_ipa_banner(apps, schema_editor):
    """
    Detail can be following this card:
    https://juloprojects.atlassian.net/browse/RUS1-2194
    """

    is_exist = ExperimentSetting.objects.filter(
        code=ExperimentConst.FDC_IPA_BANNER_EXPERIMENT
    ).exists()
    if not is_exist:
        ExperimentSetting.objects.create(
            code=ExperimentConst.FDC_IPA_BANNER_EXPERIMENT,
            name="FDC IPA Banner Experiment",
            is_active=False,
            is_permanent=False,
            start_date=timezone.localtime(timezone.now()),
            end_date=timezone.localtime(timezone.now()),
            criteria={
                "customer_id": [0, 1, 2, 3, 4, 5, 6, 7, 8, 9],
                "target_version": ">=8.11.0"
            },
            type="IPA Banner",
        )


class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.RunPython(add_new_experiment_for_ipa_banner, migrations.RunPython.noop)
    ]
