# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2024-11-01 09:23
from __future__ import unicode_literals

from django.db import migrations, models
import juloserver.julocore.customized_psycopg2.models


class Migration(migrations.Migration):

    dependencies = []

    operations = [
        migrations.CreateModel(
            name='OneKlikBcaRepaymentTransaction',
            fields=[
                ('cdate', models.DateTimeField(auto_now_add=True)),
                ('udate', models.DateTimeField(auto_now=True)),
                (
                    'id',
                    juloserver.julocore.customized_psycopg2.models.BigAutoField(
                        db_column='oneklik_bca_repayment_transaction_id',
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                ('account_payment_id', models.BigIntegerField()),
                ('partner_reference_no', models.TextField(db_index=True, unique=True)),
                ('reference_no', models.TextField(blank=True, null=True)),
                ('amount', models.BigIntegerField()),
                ('status', models.TextField(blank=True, null=True)),
                ('status_description', models.TextField(blank=True, null=True)),
                ('charge_token', models.TextField(blank=True, null=True)),
            ],
            options={
                'db_table': 'oneklik_bca_repayment_transaction',
                'managed': False,
            },
        ),
    ]
