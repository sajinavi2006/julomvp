# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2024-05-15 08:27
from __future__ import unicode_literals

from dateutil.relativedelta import relativedelta
from django.db import migrations
from django.utils import timezone

from juloserver.julo.models import ExperimentSetting
from juloserver.julo.constants import ExperimentConst


def create_data(apps, schema_editor):

    if not ExperimentSetting.objects.filter(
        code=ExperimentConst.OFFLINE_ACTIVATION_REFERRAL_CODE,
    ).exists():
        now = timezone.localtime(timezone.now())
        ExperimentSetting.objects.create(
            is_active=False,
            code=ExperimentConst.OFFLINE_ACTIVATION_REFERRAL_CODE,
            name="Offline Activation Referral Code",
            start_date=now,
            end_date=now + relativedelta(days=30),
            schedule="",
            action="",
            type="formula",
            criteria={'referral_code': 'JULO123', 'minimum_limit': 500000},
        )


class Migration(migrations.Migration):

    dependencies = []

    operations = [migrations.RunPython(create_data, migrations.RunPython.noop)]
