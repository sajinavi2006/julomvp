# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2024-03-12 08:54
from __future__ import unicode_literals

import datetime
from django.db import migrations, models
import django.db.models.deletion
from django.utils.timezone import utc


class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.AddField(
            model_name='shopeescoring',
            name='passed_reason',
            field=models.CharField(blank=True, max_length=255, null=True),
        ),
    ]
