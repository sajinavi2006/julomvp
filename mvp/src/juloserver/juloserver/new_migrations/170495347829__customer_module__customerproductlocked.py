# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2024-01-11 06:11
from __future__ import unicode_literals

import django.contrib.postgres.fields.jsonb
from django.db import migrations, models
import juloserver.julocore.customized_psycopg2.models


class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.CreateModel(
            name='CustomerProductLocked',
            fields=[
                ('cdate', models.DateTimeField(auto_now_add=True)),
                ('udate', models.DateTimeField(auto_now=True)),
                ('id', juloserver.julocore.customized_psycopg2.models.BigAutoField(db_column='customer_product_lock_id', primary_key=True, serialize=False)),
                ('customer_id', models.BigIntegerField(blank=True, db_index=True, null=True)),
                ('product_locked_info_old', django.contrib.postgres.fields.jsonb.JSONField(blank=True, default=list, null=True)),
                ('product_locked_info_new', django.contrib.postgres.fields.jsonb.JSONField(blank=True, default=list, null=True)),
            ],
            options={
                'db_table': 'customer_product_locked',
                'managed': False,
            },
        ),
    ]
