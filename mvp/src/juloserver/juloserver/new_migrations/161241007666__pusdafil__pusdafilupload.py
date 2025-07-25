# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2021-02-04 03:41
from __future__ import unicode_literals

import django.contrib.postgres.fields.jsonb
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
    ]

    operations = [
        migrations.CreateModel(
            name='PusdafilUpload',
            fields=[
                ('cdate', models.DateTimeField(auto_now_add=True)),
                ('udate', models.DateTimeField(auto_now=True)),
                ('id', models.AutoField(db_column='pusdafil_upload_id', primary_key=True, serialize=False)),
                ('identifier', models.BigIntegerField(default=0, null=True)),
                ('retry_count', models.IntegerField(default=0, null=True)),
                ('status', models.CharField(blank=True, choices=[('initiated', 'initiated'), ('queried', 'queried'), ('sent_error', 'sent_error'), ('sent_success', 'sent_success'), ('api_failed', 'api_failed')], max_length=20, null=True, verbose_name='Status')),
                ('error', django.contrib.postgres.fields.jsonb.JSONField(blank=True, null=True)),
                ('upload_data', django.contrib.postgres.fields.jsonb.JSONField(blank=True, null=True)),
            ],
            options={
                'db_table': 'pusdafil_upload',
            },
        ),
    ]
