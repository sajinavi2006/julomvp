# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2024-02-20 06:11
from __future__ import unicode_literals

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.AddField(
            model_name='promocode',
            name='promo_code_daily_usage_count',
            field=models.PositiveIntegerField(default=0),
        ),
    ]
