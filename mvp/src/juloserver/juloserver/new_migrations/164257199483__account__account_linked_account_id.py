# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2022-01-19 05:59
from __future__ import unicode_literals

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.AddField(
            model_name='account',
            name='linked_account_id',
            field=models.TextField(blank=True, null=True),
        ),
    ]
