# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2021-01-06 07:26
from __future__ import unicode_literals

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.AddField(
            model_name='account',
            name='app_version',
            field=models.TextField(blank=True, null=True),
        ),
    ]
