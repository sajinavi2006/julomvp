# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2024-01-15 08:00
from __future__ import unicode_literals

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.AddField(
            model_name='dialertask',
            name='processed_by',
            field=models.TextField(blank=True, default='mvp', null=True),
        ),
    ]
