# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2022-08-23 06:19
from __future__ import unicode_literals

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.AddField(
            model_name='account',
            name='is_payday_changed',
            field=models.BooleanField(default=False),
        ),
    ]
