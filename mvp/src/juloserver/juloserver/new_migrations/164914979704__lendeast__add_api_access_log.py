# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2022-04-05 09:09
from __future__ import unicode_literals

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    initial = True

    dependencies = [
    ]

    operations = [
        migrations.CreateModel(
            name='LendeastAPIRequest',
            fields=[
                ('cdate', models.DateTimeField(auto_now_add=True)),
                ('udate', models.DateTimeField(auto_now=True)),
                ('id', models.AutoField(db_column='lendeast_api_request_id', primary_key=True, serialize=False)),
                ('status_code', models.IntegerField()),
                ('status_message', models.TextField()),
                ('request_ts', models.DateTimeField()),
                ('response_ts', models.DateTimeField()),
                ('statement_month', models.TextField()),
                ('outstanding_amount', models.BigIntegerField()),
                ('total_loan', models.IntegerField()),
            ],
            options={
                'db_table': 'lendeast_api_request',
            },
        ),
        migrations.CreateModel(
            name='LendeastLoanRequest',
            fields=[
                ('cdate', models.DateTimeField(auto_now_add=True)),
                ('udate', models.DateTimeField(auto_now=True)),
                ('id', models.AutoField(db_column='lendeast_loan_request_id', primary_key=True, serialize=False)),
                ('loan_id', models.BigIntegerField()),
                ('outstanding_amount', models.BigIntegerField()),
                ('api_request', models.ForeignKey(db_column='lendeast_api_request_id', on_delete=django.db.models.deletion.DO_NOTHING, to='lendeast.LendeastAPIRequest')),
            ],
            options={
                'db_table': 'lendeast_loan_request',
            },
        ),
    ]
