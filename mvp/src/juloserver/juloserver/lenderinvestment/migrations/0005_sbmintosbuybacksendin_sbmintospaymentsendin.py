# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2020-01-13 07:05
from __future__ import unicode_literals

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('lenderinvestment', '0004_add_exchange_rate_to_mintos_loan_list'),
    ]

    operations = [
        migrations.CreateModel(
            name='SbMintosBuybackSendin',
            fields=[
                ('id', models.AutoField(db_column='mintos_buyback_send_in_id', primary_key=True, serialize=False)),
                ('application_xid', models.BigIntegerField(blank=True, null=True)),
                ('buyback_date', models.DateField()),
                ('purpose', models.CharField(blank=True, max_length=100, null=True)),
                ('buyback_amount', models.BigIntegerField(blank=True, null=True)),
                ('cdate', models.DateTimeField(auto_now_add=True)),
            ],
            options={
                'db_table': '"sb"."mintos_buyback_send_in"',
                'managed': False,
            },
        ),
        migrations.CreateModel(
            name='SbMintosPaymentSendin',
            fields=[
                ('id', models.AutoField(db_column='mintos_payment_send_in_id', primary_key=True, serialize=False)),
                ('application_xid', models.BigIntegerField(blank=True, null=True)),
                ('loan_id', models.BigIntegerField(blank=True, null=True)),
                ('payment_id', models.BigIntegerField(blank=True, null=True)),
                ('payment_date', models.DateField()),
                ('payment_schedule_number', models.IntegerField(blank=True, null=True)),
                ('principal_amount', models.BigIntegerField(blank=True, null=True)),
                ('interest_amount', models.BigIntegerField(blank=True, null=True)),
                ('total_amount', models.BigIntegerField(blank=True, null=True)),
                ('remaining_principal', models.BigIntegerField(blank=True, null=True)),
                ('cdate', models.DateTimeField(auto_now_add=True)),
            ],
            options={
                'db_table': '"sb"."mintos_payment_send_in"',
                'managed': False,
            },
        ),
    ]
