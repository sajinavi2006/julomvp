# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2024-11-21 05:22
from __future__ import unicode_literals

from django.db import migrations

from juloserver.cootek.constants import JuloGoldFilter, CootekProductLineCodeName
from juloserver.cootek.models import CootekConfiguration


def auto_select_exclude_for_cootek(apps, schema_editor):
    CootekConfiguration.objects.filter(
        called_at__in=range(-10, 1), product=CootekProductLineCodeName.J1
    ).update(julo_gold=JuloGoldFilter.EXCLUDE.value)


class Migration(migrations.Migration):

    dependencies = []

    operations = [
        migrations.RunPython(auto_select_exclude_for_cootek, migrations.RunPython.noop),
    ]
