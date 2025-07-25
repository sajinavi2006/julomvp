# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2024-09-23 16:05
from __future__ import unicode_literals

import django.contrib.postgres.fields.jsonb
from django.db import migrations, models
import juloserver.julocore.customized_psycopg2.models
import juloserver.partnership.models


class Migration(migrations.Migration):

    dependencies = []

    operations = [
        migrations.CreateModel(
            name='LivenessConfiguration',
            fields=[
                ('cdate', models.DateTimeField(auto_now_add=True)),
                ('udate', models.DateTimeField(auto_now=True)),
                (
                    'id',
                    juloserver.julocore.customized_psycopg2.models.BigAutoField(
                        db_column='liveness_configuration_id', primary_key=True, serialize=False
                    ),
                ),
                ('partner_id', models.BigIntegerField(db_index=True)),
                ('client_id', models.UUIDField(db_index=True, editable=False, unique=True)),
                ('api_key', models.TextField(blank=True, null=True)),
                (
                    'detection_types',
                    django.contrib.postgres.fields.jsonb.JSONField(blank=True, null=True),
                ),
                (
                    'whitelisted_domain',
                    django.contrib.postgres.fields.jsonb.JSONField(blank=True, null=True),
                ),
                ('provider', models.CharField(blank=True, max_length=100, null=True)),
                (
                    'platform',
                    models.CharField(
                        blank=True,
                        help_text='This is used to explain the platform used as web/ios/android',
                        max_length=100,
                        null=True,
                    ),
                ),
                ('is_active', models.BooleanField(default=False)),
            ],
            options={
                'db_table': 'liveness_configuration',
                'managed': False,
            },
        ),
        migrations.CreateModel(
            name='LivenessImage',
            fields=[
                ('cdate', models.DateTimeField(auto_now_add=True)),
                ('udate', models.DateTimeField(auto_now=True)),
                (
                    'id',
                    models.AutoField(
                        db_column='liveness_image_id', primary_key=True, serialize=False
                    ),
                ),
                (
                    'image',
                    models.ImageField(
                        blank=True,
                        db_column='internal_path',
                        null=True,
                        upload_to=juloserver.partnership.models.upload_to,
                    ),
                ),
                ('image_type', models.CharField(blank=True, max_length=50, null=True)),
                (
                    'image_status',
                    models.IntegerField(
                        choices=[(-1, 'Inactive'), (0, 'Active'), (1, 'Resubmission Required')],
                        default=0,
                    ),
                ),
                ('url', models.CharField(max_length=200)),
                (
                    'service',
                    models.CharField(
                        choices=[('s3', 's3'), ('oss', 'oss')], default='oss', max_length=50
                    ),
                ),
                (
                    'image_source',
                    models.BigIntegerField(
                        db_column='image_source',
                        db_index=True,
                        help_text='This field is used to establish a relationship with the liveness_result table',
                    ),
                ),
            ],
            options={
                'db_table': 'liveness_image',
                'managed': False,
            },
        ),
        migrations.CreateModel(
            name='LivenessResult',
            fields=[
                ('cdate', models.DateTimeField(auto_now_add=True)),
                ('udate', models.DateTimeField(auto_now=True)),
                (
                    'id',
                    juloserver.julocore.customized_psycopg2.models.BigAutoField(
                        db_column='liveness_result_id', primary_key=True, serialize=False
                    ),
                ),
                ('liveness_configuration_id', models.BigIntegerField(db_index=True)),
                ('client_id', models.UUIDField(db_index=True)),
                (
                    'image_ids',
                    django.contrib.postgres.fields.jsonb.JSONField(blank=True, null=True),
                ),
                (
                    'platform',
                    models.CharField(
                        help_text='This is used to explain the platform used as web/ios/android',
                        max_length=100,
                    ),
                ),
                (
                    'detection_types',
                    models.CharField(help_text='detection types passive or smile', max_length=100),
                ),
                ('score', models.FloatField(blank=True, null=True)),
                ('status', models.CharField(blank=True, max_length=100, null=True)),
                ('reference_id', models.UUIDField(editable=False, unique=True)),
            ],
            options={
                'db_table': 'liveness_result',
                'managed': False,
            },
        ),
        migrations.CreateModel(
            name='LivenessResultMetadata',
            fields=[
                ('cdate', models.DateTimeField(auto_now_add=True)),
                ('udate', models.DateTimeField(auto_now=True)),
                (
                    'id',
                    juloserver.julocore.customized_psycopg2.models.BigAutoField(
                        db_column='liveness_result_metadata_id', primary_key=True, serialize=False
                    ),
                ),
                ('liveness_result_id', models.BigIntegerField(db_index=True)),
                (
                    'config_applied',
                    django.contrib.postgres.fields.jsonb.JSONField(blank=True, null=True),
                ),
                (
                    'response_data',
                    django.contrib.postgres.fields.jsonb.JSONField(blank=True, null=True),
                ),
            ],
            options={
                'db_table': 'liveness_result_metadata',
                'managed': False,
            },
        ),
    ]
