# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2022-08-10 14:58
from __future__ import unicode_literals

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.AddField(
            model_name='account',
            name='is_ldde',
            field=models.BooleanField(default=False),
        ),
    ]
