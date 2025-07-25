# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2024-05-16 09:01
from __future__ import unicode_literals

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = []

    operations = [
        migrations.CreateModel(
            name='CollectionDialerTaskSummaryAPI',
            fields=[
                ('cdate', models.DateTimeField(auto_now_add=True)),
                ('udate', models.DateTimeField(auto_now=True)),
                (
                    'id',
                    models.AutoField(
                        db_column='collection_dialer_task_summary_api_id',
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                ('date', models.DateField(blank=True, null=True)),
                ('external_task_identifier', models.TextField(blank=True, null=True)),
                ('external_task_name', models.TextField(blank=True, null=True)),
                ('total_api', models.IntegerField(default=0)),
                ('total_before_retro', models.IntegerField(default=0)),
                ('total_after_retro', models.IntegerField(default=0)),
            ],
            options={
                'db_table': 'collection_dialer_task_summary_api',
            },
        ),
    ]
