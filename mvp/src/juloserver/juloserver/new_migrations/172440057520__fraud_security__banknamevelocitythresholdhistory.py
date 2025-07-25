# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2024-08-23 08:09
from __future__ import unicode_literals

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = []

    operations = [
        migrations.CreateModel(
            name='BankNameVelocityThresholdHistory',
            fields=[
                ('cdate', models.DateTimeField(auto_now_add=True)),
                ('udate', models.DateTimeField(auto_now=True)),
                (
                    'id',
                    models.AutoField(
                        db_column='bank_name_velocity_threshold_history_id',
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                ('threshold_date', models.DateTimeField(blank=True, null=True)),
                ('threshold', models.FloatField(blank=True, null=True)),
            ],
            options={
                'db_table': 'bank_name_velocity_threshold_history',
            },
        ),
    ]
