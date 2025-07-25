# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2025-01-06 09:01
from __future__ import unicode_literals

import django.contrib.postgres.fields.jsonb
from django.db import migrations, models
import juloserver.julocore.customized_psycopg2.models


class Migration(migrations.Migration):

    dependencies = []

    operations = [
        migrations.CreateModel(
            name='PartnershipClikModelResult',
            fields=[
                ('cdate', models.DateTimeField(auto_now_add=True)),
                ('udate', models.DateTimeField(auto_now=True)),
                (
                    'id',
                    juloserver.julocore.customized_psycopg2.models.BigAutoField(
                        db_column='partnership_clik_model_result_id',
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                ('application_id', models.BigIntegerField(db_index=True)),
                ('pgood', models.FloatField()),
                ('status', models.CharField(max_length=100)),
                ('notes', models.TextField(blank=True, null=True)),
                ('metadata', django.contrib.postgres.fields.jsonb.JSONField(blank=True, null=True)),
            ],
            options={
                'db_table': 'partnership_clik_model_result',
                'managed': False,
            },
        ),
    ]
