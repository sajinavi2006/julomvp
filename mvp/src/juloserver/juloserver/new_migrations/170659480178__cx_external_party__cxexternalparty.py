# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2024-02-21 07:21
from __future__ import unicode_literals

from django.db import migrations, models
import django.db.models.manager


class Migration(migrations.Migration):

    initial = True

    dependencies = [
    ]

    operations = [
        migrations.CreateModel(
            name='CXExternalParty',
            fields=[
                ('cdate', models.DateTimeField(auto_now_add=True)),
                ('udate', models.DateTimeField(auto_now=True)),
                ('id', models.AutoField(db_column='cx_external_parties_id', primary_key=True, serialize=False)),
                ('name', models.CharField(max_length=100, unique=True)),
                ('expiry_date', models.DateTimeField(blank=True, help_text='Default is None for lifetime period', null=True)),
                ('is_active', models.BooleanField(default=True, help_text='If the API key is not active, cannot use it anymore')),
            ],
            options={
                'db_table': 'cx_external_parties',
            },
            managers=[
                ('api_key', django.db.models.manager.Manager()),
            ],
        ),
    ]
