# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2023-03-08 09:30
from __future__ import unicode_literals

import django.contrib.postgres.fields
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.AddField(
            model_name='emulatorcheck',
            name='error_occurrences',
            field=django.contrib.postgres.fields.ArrayField(base_field=models.TextField(), blank=True, default=None, null=True, size=None),
        ),
    ]
