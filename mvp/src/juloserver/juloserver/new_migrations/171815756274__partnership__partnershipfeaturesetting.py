# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2024-06-12 01:59
from __future__ import unicode_literals

import django.contrib.postgres.fields.jsonb
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = []

    operations = [
        migrations.CreateModel(
            name='PartnershipFeatureSetting',
            fields=[
                ('cdate', models.DateTimeField(auto_now_add=True)),
                ('udate', models.DateTimeField(auto_now=True)),
                (
                    'id',
                    models.AutoField(
                        db_column='partnership_feature_setting_id',
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                ('feature_name', models.CharField(max_length=100)),
                ('is_active', models.BooleanField(default=False)),
                (
                    'parameters',
                    django.contrib.postgres.fields.jsonb.JSONField(blank=True, null=True),
                ),
                ('category', models.CharField(max_length=100)),
                ('description', models.CharField(max_length=200)),
            ],
            options={
                'db_table': 'partnership_feature_setting',
                'managed': False,
            },
        ),
    ]
