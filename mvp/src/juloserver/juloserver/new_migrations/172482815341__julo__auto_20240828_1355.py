# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2024-08-28 06:55
from __future__ import unicode_literals

import django.contrib.postgres.fields.jsonb
import django.core.validators
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.AddField(
            model_name='device',
            name='julo_device_id',
            field=models.TextField(blank=True, null=True),
        ),
    ]
