# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2024-06-17 22:40
from dateutil.relativedelta import relativedelta
from django.db import migrations
from django.utils import timezone

from juloserver.julo.models import ExperimentSetting
from juloserver.julo.constants import ExperimentConst


def run(apps, schema_editor):
    if not ExperimentSetting.objects.filter(
        code=ExperimentConst.LBS_130_BYPASS,
    ).exists():
        now = timezone.localtime(timezone.now())
        ExperimentSetting.objects.create(
            is_active=False,
            code=ExperimentConst.LBS_130_BYPASS,
            name="LBS 130 BYPASS",
            start_date=now,
            end_date=now + relativedelta(days=30),
            schedule="",
            action="",
            type="underwriting",
            criteria={
                'limit_total_of_application_min_affordability': 700,
                'limit_total_of_application_swap_out_dukcapil': 700,
            },
        )


class Migration(migrations.Migration):

    dependencies = []

    operations = [migrations.RunPython(run, migrations.RunPython.noop)]
