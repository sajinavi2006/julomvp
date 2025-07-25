# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2019-02-21 15:35
from __future__ import unicode_literals

import django.core.validators
from django.db import migrations, models
import juloserver.julo.models


class Migration(migrations.Migration):

    dependencies = [
        ('julo', '0356_reload_workflow_status_path_for_v3'),
    ]

    operations = [
        migrations.AddField(
            model_name='customer',
            name='is_digisign_activated',
            field=models.NullBooleanField(),
        ),
        migrations.AddField(
            model_name='customer',
            name='is_digisign_registered',
            field=models.NullBooleanField(),
        ),
    ]
