# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2022-05-24 17:34
from __future__ import unicode_literals

import django.contrib.postgres.fields.jsonb
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.AddField(
            model_name='moengageupload',
            name='attributes',
            field=django.contrib.postgres.fields.jsonb.JSONField(blank=True, default=list, null=True),
        ),
        migrations.AddField(
            model_name='moengageupload',
            name='time_sent',
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
