# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2021-11-22 06:36
from __future__ import unicode_literals

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.AddField(
            model_name='autodebetaccount',
            name='deleted_request_ts',
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
