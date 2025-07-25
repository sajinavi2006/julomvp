# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2024-08-15 10:43
from __future__ import unicode_literals

from django.db import migrations, models
import juloserver.julocore.customized_psycopg2.models


class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.CreateModel(
            name='SalesOpsPrepareData',
            fields=[
                ('cdate', models.DateTimeField(auto_now_add=True)),
                ('udate', models.DateTimeField(auto_now=True)),
                ('id', models.AutoField(db_column='sales_ops_prepare_data_id', primary_key=True, serialize=False)),
                ('account_id', models.BigIntegerField()),
                ('customer_id', models.BigIntegerField()),
                ('customer_type', models.TextField(blank=True, choices=[('ftc', 'Ftc'), ('repeat_os', 'Repeat_Os'), ('repeat_no_os', 'Repeat_No_Os')], null=True)),
                ('application_history_x190_cdate', models.DateTimeField()),
                ('latest_loan_fund_transfer_ts', models.DateTimeField()),
                ('available_limit', models.BigIntegerField(default=0)),
            ],
            options={
                'db_table': '"ana"."sales_ops_prepare_data"',
                'managed': False,
            },
        ),
        migrations.CreateModel(
            name='SalesOpsRMScoringConfig',
            fields=[
                ('cdate', models.DateTimeField(auto_now_add=True)),
                ('udate', models.DateTimeField(auto_now=True)),
                ('id', juloserver.julocore.customized_psycopg2.models.BigAutoField(db_column='sales_ops_rm_scoring_id', primary_key=True, serialize=False)),
                ('criteria', models.TextField(choices=[('recency', 'Recency'), ('monetary', 'Monetary')], db_index=True)),
                ('min_value', models.BigIntegerField(blank=True, null=True)),
                ('max_value', models.BigIntegerField(blank=True, null=True)),
                ('customer_type', models.TextField(blank=True, choices=[('ftc', 'Ftc'), ('repeat_os', 'Repeat_Os'), ('repeat_no_os', 'Repeat_No_Os')], null=True)),
                ('field_name', models.TextField(blank=True, null=True)),
                ('score', models.SmallIntegerField()),
                ('is_active', models.BooleanField(default=False)),
            ],
            options={
                'db_table': 'sales_ops_rm_scoring_config',
                'managed': False,
            },
        ),
    ]
