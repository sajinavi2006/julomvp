# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2021-11-02 05:21
from __future__ import unicode_literals

from django.db import migrations, models
import django.db.models.deletion
import juloserver.julocore.customized_psycopg2.models


class Migration(migrations.Migration):

    dependencies = [
    ]

    database_operations = [
        migrations.CreateModel(
            name='LoanAdjustedRate',
            fields=[
                ('cdate', models.DateTimeField(auto_now_add=True)),
                ('udate', models.DateTimeField(auto_now=True)),
                ('id', models.AutoField(db_column='loan_adjusted_rate_id', primary_key=True, serialize=False)),
                ('adjusted_monthly_interest_rate', models.FloatField()),
                ('adjusted_provision_rate', models.FloatField()),
                ('max_fee', models.FloatField()),
                ('simple_fee', models.FloatField()),
                ('loan', juloserver.julocore.customized_psycopg2.models.BigForeignKey(db_column='loan_id', on_delete=django.db.models.deletion.DO_NOTHING, to='julo.Loan', unique=True)),
            ],
            options={
                'db_table': 'loan_adjusted_rate',
            },
        ),
    ]

    state_operations = [
        migrations.CreateModel(
            name='LoanAdjustedRate',
            fields=[
                ('cdate', models.DateTimeField(auto_now_add=True)),
                ('udate', models.DateTimeField(auto_now=True)),
                ('id', models.AutoField(db_column='loan_adjusted_rate_id', primary_key=True,
                                        serialize=False)),
                ('adjusted_monthly_interest_rate', models.FloatField()),
                ('adjusted_provision_rate', models.FloatField()),
                ('max_fee', models.FloatField()),
                ('simple_fee', models.FloatField()),
                ('loan', models.OneToOneField(db_column='loan_id',
                                              on_delete=django.db.models.deletion.DO_NOTHING,
                                              to='julo.Loan')),
            ],
            options={
                'db_table': 'loan_adjusted_rate',
            },
        ),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=database_operations,
            state_operations=state_operations
        )

    ]
