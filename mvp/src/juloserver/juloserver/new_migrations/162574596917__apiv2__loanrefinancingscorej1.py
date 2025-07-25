# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2021-07-08 12:06
from __future__ import unicode_literals

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.CreateModel(
            name='LoanRefinancingScoreJ1',
            fields=[
                ('id', models.BigIntegerField(primary_key=True, serialize=False)),
                ('fullname', models.TextField()),
                ('email', models.EmailField(blank=True, max_length=254, null=True)),
                ('monthly_income', models.BigIntegerField(default=0)),
                ('total_expense', models.BigIntegerField(default=0)),
                ('total_due_amt', models.BigIntegerField(default=0)),
                ('outstanding_principal', models.BigIntegerField(default=0)),
                ('outstanding_interest', models.BigIntegerField(default=0)),
                ('outstanding_latefee', models.BigIntegerField(default=0)),
                ('rem_installment', models.IntegerField(db_column='rem_installment')),
                ('ability_score', models.FloatField(db_column='ability_score')),
                ('willingness_score', models.FloatField(db_column='willingness_score')),
                ('oldest_payment_num', models.IntegerField(db_column='oldest_payment_num')),
                ('oldest_due_date', models.DateField(blank=True, null=True)),
                ('is_covid_risky', models.NullBooleanField()),
                ('bucket', models.TextField()),
            ],
            options={
                'db_table': '"ana"."loan_refinancing_score_j1"',
                'managed': False,
            },
        ),
    ]
