# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2021-04-19 02:21
from __future__ import unicode_literals

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.AddField(
            model_name='skiptracehistory',
            name='caller_id',
            field=models.TextField(blank=True, null=True),
        ),
    ]
