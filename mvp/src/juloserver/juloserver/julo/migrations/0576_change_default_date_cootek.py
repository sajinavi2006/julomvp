# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2019-12-13 07:44
from __future__ import unicode_literals

from django.conf import settings
import django.core.validators
from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone
import juloserver.julo.models


class Migration(migrations.Migration):

    dependencies = [
        ('julo', '0575_add_task_status_cootek_robocall'),
    ]

    operations = [
        migrations.AlterField(
            model_name='cootekrobocall',
            name='cootek_event_date',
            field=models.DateTimeField(blank=True, default=django.utils.timezone.now, null=True),
        ),
    ]
