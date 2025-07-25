# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2018-03-13 08:16
from __future__ import unicode_literals

import django.contrib.postgres.fields
import django.contrib.postgres.fields.jsonb
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('apiv2', '0004_pdcreditmodelresult'),
    ]

    operations = [
        migrations.CreateModel(
            name='EtlStatus',
            fields=[
                (
                    'id',
                    models.BigIntegerField(
                        db_column='etl_status_id', primary_key=True, serialize=False
                    ),
                ),
                ('application_id', models.BigIntegerField(db_index=True)),
                (
                    'started_tasks',
                    django.contrib.postgres.fields.ArrayField(
                        base_field=models.CharField(max_length=100), default=list, size=None
                    ),
                ),
                (
                    'executed_tasks',
                    django.contrib.postgres.fields.ArrayField(
                        base_field=models.CharField(max_length=100), default=list, size=None
                    ),
                ),
                ('errors', django.contrib.postgres.fields.jsonb.JSONField(default=dict)),
                ('meta_data', django.contrib.postgres.fields.jsonb.JSONField(default=dict)),
            ],
            options={
                'db_table': '"ana"."etl_status"',
                'managed': False,
            },
        ),
    ]
