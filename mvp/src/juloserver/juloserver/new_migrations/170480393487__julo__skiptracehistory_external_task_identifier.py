# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2024-01-09 12:38
from __future__ import unicode_literals

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.AddField(
            model_name='skiptracehistory',
            name='external_task_identifier',
            field=models.TextField(blank=True, db_index=True, null=True),
        ),
    ]
