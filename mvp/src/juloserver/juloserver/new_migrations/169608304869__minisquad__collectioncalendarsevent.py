# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2023-09-30 14:10
from __future__ import unicode_literals

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.CreateModel(
            name='CollectionCalendarsEvent',
            fields=[
                ('cdate', models.DateTimeField(auto_now_add=True)),
                ('udate', models.DateTimeField(auto_now=True)),
                ('id', models.AutoField(db_column='collection_calendars_event_id', primary_key=True, serialize=False)),
                ('request', models.TextField(blank=True, null=True)),
                ('google_calendar_event_id', models.CharField(max_length=255, unique=True)),
            ],
            options={
                'db_table': 'collection_calendars_event',
            },
        ),
    ]
