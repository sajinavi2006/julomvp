# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2021-12-17 07:27
from __future__ import unicode_literals

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.CreateModel(
            name='PdClcsPrimeResult',
            fields=[
                ('id', models.AutoField(db_column='pd_clcs_prime_result_id', primary_key=True, serialize=False)),
                ('customer_id', models.BigIntegerField(blank=True, db_index=True, null=True)),
                ('partition_date', models.DateField(blank=True, null=True)),
                ('clcs_prime_score', models.FloatField()),
                ('a_score', models.FloatField()),
                ('a_score_version', models.CharField(blank=True, max_length=256, null=True)),
                ('b_score', models.FloatField()),
                ('b_score_version', models.CharField(blank=True, max_length=256, null=True)),
            ],
            options={
                'db_table': '"ana"."pd_clcs_prime_result"',
                'managed': False,
            },
        ),
    ]
