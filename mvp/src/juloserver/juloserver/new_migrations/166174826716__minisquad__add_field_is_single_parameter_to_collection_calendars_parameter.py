# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2022-08-29 04:44
from __future__ import unicode_literals

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.AddField(
            model_name='collectioncalendarsparameter',
            name='is_single_parameter',
            field=models.BooleanField(default=False),
        ),
    ]
