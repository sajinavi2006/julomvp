# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2021-11-26 08:35
from __future__ import unicode_literals

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.AddField(
            model_name='dashboardbuckets',
            name='app_overpaid_verification',
            field=models.IntegerField(default=0),
        ),
    ]
