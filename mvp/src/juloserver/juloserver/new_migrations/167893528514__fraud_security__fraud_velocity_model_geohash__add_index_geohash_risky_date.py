# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2023-03-16 02:54
from __future__ import unicode_literals

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.AlterField(
            model_name='fraudvelocitymodelgeohash',
            name='geohash',
            field=models.TextField(blank=True, db_index=True, null=True),
        ),
        migrations.AlterField(
            model_name='fraudvelocitymodelgeohash',
            name='risky_date',
            field=models.DateField(blank=True, db_index=True, null=True),
        ),
    ]
