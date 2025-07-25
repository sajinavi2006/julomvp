# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2023-12-07 07:22
from __future__ import unicode_literals

from django.db import migrations, models
import juloserver.julocore.customized_psycopg2.models


class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.CreateModel(
            name='BpjsAlertLog',
            fields=[
                ('cdate', models.DateTimeField(auto_now_add=True)),
                ('udate', models.DateTimeField(auto_now=True)),
                ('id', juloserver.julocore.customized_psycopg2.models.BigAutoField(db_column='bpjs_alert_log_id', primary_key=True, serialize=False)),
                ('customer_id', models.BigIntegerField(db_index=True)),
                ('provider', models.CharField(max_length=50)),
                ('log', models.TextField()),
            ],
            options={
                'db_table': 'bpjs_alert_log',
                'managed': False,
            },
        ),
    ]
