# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2021-03-17 04:00
from __future__ import unicode_literals

from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
    ]

    operations = [
        migrations.CreateModel(
            name='PdBankScrapeModelResult',
            fields=[
                ('cdate', models.DateTimeField(auto_now_add=True)),
                ('udate', models.DateTimeField(auto_now=True)),
                ('id', models.BigIntegerField(db_column='pd_bank_scrape_model_result_id', primary_key=True, serialize=False)),
                ('application_id', models.BigIntegerField(db_index=True)),
                ('sd_bank_statement_detail_id', models.BigIntegerField()),
                ('probability_is_salary', models.FloatField()),
                ('model_version', models.CharField(blank=True, max_length=200, null=True)),
                ('model_threshold', models.FloatField(blank=True, null=True)),
                ('model_selection_version', models.BigIntegerField(blank=True, null=True)),
                ('transaction_amount', models.BigIntegerField(blank=True, null=True)),
                ('stated_income', models.BigIntegerField(blank=True, null=True)),
                ('max_deviation_income', models.FloatField(blank=True, null=True)),
                ('processed_income', models.BigIntegerField(blank=True, null=True)),
            ],
            options={
                'db_table': '"ana"."pd_bank_scrape_model_result"',
                'managed': False,
            },
        ),
    ]
