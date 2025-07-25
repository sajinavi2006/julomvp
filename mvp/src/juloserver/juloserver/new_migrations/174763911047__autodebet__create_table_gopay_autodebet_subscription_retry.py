# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2025-05-19 07:18
from __future__ import unicode_literals

from django.db import migrations, models
import juloserver.julocore.customized_psycopg2.models


class Migration(migrations.Migration):

    dependencies = []

    operations = [
        migrations.CreateModel(
            name='GopayAutodebetSubscriptionRetry',
            fields=[
                ('cdate', models.DateTimeField(auto_now_add=True)),
                ('udate', models.DateTimeField(auto_now=True)),
                (
                    'id',
                    juloserver.julocore.customized_psycopg2.models.BigAutoField(
                        db_column='gopay_autodebet_subscription_retry_id',
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                ('account_payment_id', models.BigIntegerField(blank=True, null=True)),
                ('error', models.TextField(blank=True, null=True)),
                ('is_retried', models.BooleanField(default=False)),
            ],
            options={
                'db_table': 'gopay_autodebet_subscription_retry',
                'managed': False,
            },
        ),
    ]
