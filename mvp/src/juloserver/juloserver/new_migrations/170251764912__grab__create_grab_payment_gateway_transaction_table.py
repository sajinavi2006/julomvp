# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2023-12-14 01:34
from __future__ import unicode_literals

from django.db import migrations, models
import django.db.models.deletion
import juloserver.julocore.customized_psycopg2.models


class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.CreateModel(
            name='PaymentGatewayTransaction',
            fields=[
                ('cdate', models.DateTimeField(auto_now_add=True)),
                ('udate', models.DateTimeField(auto_now=True)),
                ('id', juloserver.julocore.customized_psycopg2.models.BigAutoField(db_column='payment_gateway_transaction_id', primary_key=True, serialize=False)),
                ('disbursement_id', models.BigIntegerField()),
                ('correlation_id', models.CharField(blank=True, max_length=50, null=True)),
                ('transaction_id', models.CharField(blank=True, max_length=50, null=True)),
                ('status', models.CharField(blank=True, max_length=25, null=True)),
                ('reason', models.TextField(blank=True, null=True)),
                ('payment_gateway_vendor', models.ForeignKey(blank=True, db_column='payment_gateway_vendor_id', null=True, on_delete=django.db.models.deletion.DO_NOTHING, to='grab.PaymentGatewayVendor')),
            ],
            options={
                'db_table': 'payment_gateway_transaction',
            },
        ),
    ]
