# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2024-01-29 07:24
from __future__ import unicode_literals

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.AddField(
            model_name='loanjulocare',
            name='insurance_premium_rate',
            field=models.FloatField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='loanjulocare',
            name='original_insurance_premium',
            field=models.BigIntegerField(blank=True, null=True),
        ),
    ]
