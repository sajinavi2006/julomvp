# -*- coding: utf-8 -*-
# Generated by Django 1.9.13 on 2023-09-14 04:52
from __future__ import unicode_literals

from django.db import migrations

from juloserver.julo.models import SkiptraceResultChoice


def load_skiptrace_result_choise(apps, schema_editor):
    data = [
        ('Whatsapp - Checklist 1', '5'),
        ('Whatsapp - Checklist 2', '5'),
        ('Whatsapp - Not Available', '5'),
    ]

    for name, weight in data:
        obj = SkiptraceResultChoice(name=name, weight=weight)
        obj.save()

class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.RunPython(load_skiptrace_result_choise, migrations.RunPython.noop)
    ]
