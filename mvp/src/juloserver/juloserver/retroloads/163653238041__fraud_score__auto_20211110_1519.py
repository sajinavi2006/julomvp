# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2021-11-05 09:20
from __future__ import unicode_literals

from django.db import migrations
from juloserver.fraud_score.tasks import bonza_rescore_5xx_hit_asynchronously


def initial_bonza_5xx_rescore(apps, schema_editor):
    bonza_rescore_5xx_hit_asynchronously(initial_rescore=True)


class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.RunPython(initial_bonza_5xx_rescore, migrations.RunPython.noop)
    ]
