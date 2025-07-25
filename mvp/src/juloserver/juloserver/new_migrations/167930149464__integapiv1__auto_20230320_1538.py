# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2023-03-20 08:38
from __future__ import unicode_literals

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    initial = True

    dependencies = [
    ]

    operations = [
        migrations.CreateModel(
            name='EscrowPaymentGateway',
            fields=[
                ('cdate', models.DateTimeField(auto_now_add=True)),
                ('udate', models.DateTimeField(auto_now=True)),
                ('id', models.AutoField(db_column='escrow_payment_gateway_id', primary_key=True, serialize=False)),
                ('owner', models.TextField()),
                ('description', models.TextField()),
            ],
            options={
                'db_table': 'escrow_payment_gateway',
            },
        ),
        migrations.CreateModel(
            name='EscrowPaymentMethod',
            fields=[
                ('cdate', models.DateTimeField(auto_now_add=True)),
                ('udate', models.DateTimeField(auto_now=True)),
                ('id', models.AutoField(db_column='escrow_payment_method_id', primary_key=True, serialize=False)),
                ('virtual_account', models.TextField(unique=True)),
                ('escrow_payment_gateway', models.ForeignKey(blank=True, db_column='escrow_payment_gateway_id', null=True, on_delete=django.db.models.deletion.DO_NOTHING, to='integapiv1.EscrowPaymentGateway')),
            ],
            options={
                'db_table': 'escrow_payment_method',
            },
        ),
        migrations.CreateModel(
            name='EscrowPaymentMethodLookup',
            fields=[
                ('cdate', models.DateTimeField(auto_now_add=True)),
                ('udate', models.DateTimeField(auto_now=True)),
                ('id', models.AutoField(db_column='escrow_payment_method_lookup_id', primary_key=True, serialize=False)),
                ('payment_method_code', models.TextField()),
                ('payment_method_name', models.TextField()),
            ],
            options={
                'db_table': 'escrow_payment_method_lookup',
            },
        ),
        migrations.AddField(
            model_name='escrowpaymentmethod',
            name='escrow_payment_method_lookup',
            field=models.ForeignKey(blank=True, db_column='escrow_payment_method_lookup_id', null=True, on_delete=django.db.models.deletion.DO_NOTHING, to='integapiv1.EscrowPaymentMethodLookup'),
        ),
    ]
