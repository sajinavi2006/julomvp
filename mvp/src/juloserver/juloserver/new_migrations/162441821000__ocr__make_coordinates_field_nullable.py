# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2021-06-23 03:16
from __future__ import unicode_literals

import django.contrib.postgres.fields.jsonb
from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.AlterField(
            model_name='ocrimageresult',
            name='coordinates',
            field=django.contrib.postgres.fields.jsonb.JSONField(blank=True, default=dict, null=True),
        ),
    ]
