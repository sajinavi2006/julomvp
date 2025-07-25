# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2022-02-09 02:45
from __future__ import unicode_literals
from unicodedata import category

from django.db import migrations
from juloserver.julo.models import FeatureSetting
from juloserver.julo.constants import FeatureNameConst


def add_new_feature_bss_channeling_cutoff(apps, _schema_editor):
    FeatureSetting.objects.create(
        feature_name=FeatureNameConst.BSS_CHANNELING_CUTOFF,
        is_active=False,
        parameters={"cutoff_time": '19:00','opening_time':'07:00'},
        category='channeling_loan',
        description="BSS Channeling Cutoff Time")


class Migration(migrations.Migration):
    dependencies = [
    ]

    operations = [
        migrations.RunPython(add_new_feature_bss_channeling_cutoff,
                             migrations.RunPython.noop)
    ]
