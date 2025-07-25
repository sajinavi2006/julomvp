# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2024-07-22 04:43
from __future__ import unicode_literals

from django.db import migrations, models
import juloserver.julocore.customized_psycopg2.models


class Migration(migrations.Migration):

    dependencies = []

    operations = [
        migrations.CreateModel(
            name='GrabMasterLock',
            fields=[
                ('cdate', models.DateTimeField(auto_now_add=True)),
                ('udate', models.DateTimeField(auto_now=True)),
                (
                    'id',
                    juloserver.julocore.customized_psycopg2.models.BigAutoField(
                        db_column='grab_master_lock_id', primary_key=True, serialize=False
                    ),
                ),
                ('customer_id', models.BigIntegerField(blank=True, null=True)),
                ('application_id', models.BigIntegerField(blank=True, null=True)),
                ('expire_ts', models.DateTimeField()),
                ('lock_reason', models.TextField(blank=True, null=True)),
                ('last_updated', models.DateTimeField(blank=True, null=True)),
            ],
            options={
                'db_table': 'grab_master_lock',
                'managed': False,
            },
        ),
    ]
