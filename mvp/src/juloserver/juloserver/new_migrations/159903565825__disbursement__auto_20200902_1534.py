# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2020-09-02 08:34
from __future__ import unicode_literals

import django.contrib.postgres.fields.jsonb
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    initial = True

    dependencies = [
    ]

    operations = [
        migrations.CreateModel(
            name='BankNameValidationLog',
            fields=[
                ('cdate', models.DateTimeField(auto_now_add=True)),
                ('udate', models.DateTimeField(auto_now=True)),
                ('id', models.AutoField(db_column='bank_validation_log_id', primary_key=True, serialize=False)),
                ('validation_id', models.CharField(blank=True, max_length=100, null=True)),
                ('validation_status', models.CharField(default='INITIATED', max_length=20)),
                ('validated_name', models.CharField(blank=True, max_length=100, null=True)),
                ('account_number', models.CharField(max_length=100)),
                ('reason', models.CharField(blank=True, max_length=100, null=True)),
                ('method', models.CharField(max_length=50)),
                ('validation_status_old', models.CharField(default='INITIATED', max_length=20)),
                ('validated_name_old', models.CharField(blank=True, max_length=100, null=True)),
                ('account_number_old', models.CharField(blank=True, max_length=100, null=True)),
                ('reason_old', models.CharField(blank=True, max_length=100, null=True)),
                ('method_old', models.CharField(blank=True, max_length=50, null=True)),
            ],
            options={
                'db_table': 'bank_name_validation_log',
            },
        ),
        migrations.CreateModel(
            name='BcaTransactionRecord',
            fields=[
                ('cdate', models.DateTimeField(auto_now_add=True)),
                ('udate', models.DateTimeField(auto_now=True)),
                ('id', models.AutoField(db_column='bca_transaction_id', primary_key=True, serialize=False)),
                ('transaction_date', models.DateField()),
                ('reference_id', models.CharField(max_length=20)),
                ('currency_code', models.CharField(max_length=10)),
                ('amount', models.IntegerField()),
                ('beneficiary_account_number', models.CharField(max_length=100)),
                ('remark1', models.CharField(max_length=100)),
                ('status', models.CharField(blank=True, max_length=100, null=True)),
                ('error_code', models.CharField(blank=True, max_length=50, null=True)),
            ],
            options={
                'db_table': 'bca_transaction_record2',
            },
        ),
        migrations.CreateModel(
            name='Disbursement',
            fields=[
                ('cdate', models.DateTimeField(auto_now_add=True)),
                ('udate', models.DateTimeField(auto_now=True)),
                ('id', models.AutoField(db_column='disbursement_id', primary_key=True, serialize=False)),
                ('disbursement_type', models.CharField(default='loan', max_length=10)),
                ('external_id', models.CharField(max_length=50)),
                ('amount', models.BigIntegerField()),
                ('method', models.CharField(max_length=50)),
                ('disburse_id', models.CharField(blank=True, max_length=100, null=True)),
                ('disburse_status', models.CharField(default='INITIATED', max_length=50)),
                ('retry_times', models.IntegerField(default=0)),
                ('reason', models.CharField(blank=True, max_length=500, null=True)),
                ('reference_id', models.CharField(blank=True, max_length=100, null=True)),
                ('step', models.IntegerField(blank=True, null=True)),
                ('original_amount', models.BigIntegerField(null=True)),
            ],
            options={
                'db_table': 'disbursement2',
            },
        ),
        migrations.CreateModel(
            name='Disbursement2History',
            fields=[
                ('cdate', models.DateTimeField(auto_now_add=True)),
                ('udate', models.DateTimeField(auto_now=True)),
                ('id', models.AutoField(db_column='disbursement2_history_id', primary_key=True, serialize=False)),
                ('amount', models.BigIntegerField()),
                ('method', models.CharField(max_length=50)),
                ('order_id', models.CharField(blank=True, max_length=100, null=True)),
                ('idempotency_id', models.CharField(blank=True, max_length=100, null=True)),
                ('disburse_status', models.CharField(blank=True, max_length=50, null=True)),
                ('reason', models.CharField(blank=True, max_length=500, null=True)),
                ('reference_id', models.CharField(blank=True, max_length=100, null=True)),
                ('attempt', models.IntegerField(blank=True, null=True)),
                ('step', models.IntegerField(blank=True, null=True)),
                ('disbursement', models.ForeignKey(db_column='disbursement_id', on_delete=django.db.models.deletion.CASCADE, to='disbursement.Disbursement')),
            ],
            options={
                'db_table': 'disbursement2_history',
            },
        ),
        migrations.CreateModel(
            name='DisbursementHistory',
            fields=[
                ('cdate', models.DateTimeField(auto_now_add=True)),
                ('udate', models.DateTimeField(auto_now=True)),
                ('id', models.AutoField(db_column='disbursement_history_id', primary_key=True, serialize=False)),
                ('event', models.CharField(max_length=50)),
                ('field_changes', django.contrib.postgres.fields.jsonb.JSONField()),
                ('disbursement', models.ForeignKey(db_column='disbursement_id', on_delete=django.db.models.deletion.DO_NOTHING, to='disbursement.Disbursement')),
            ],
            options={
                'db_table': 'disbursement_history',
            },
        ),
        migrations.CreateModel(
            name='NameBankValidation',
            fields=[
                ('cdate', models.DateTimeField(auto_now_add=True)),
                ('udate', models.DateTimeField(auto_now=True)),
                ('id', models.AutoField(db_column='name_bank_validation_id', primary_key=True, serialize=False)),
                ('bank_code', models.CharField(max_length=100)),
                ('account_number', models.CharField(max_length=100)),
                ('name_in_bank', models.CharField(max_length=100)),
                ('method', models.CharField(max_length=50)),
                ('validation_id', models.CharField(blank=True, max_length=100, null=True)),
                ('validation_status', models.CharField(default='INITIATED', max_length=20)),
                ('validated_name', models.CharField(blank=True, max_length=100, null=True)),
                ('mobile_phone', models.CharField(max_length=20)),
                ('reason', models.CharField(blank=True, max_length=100, null=True)),
                ('attempt', models.IntegerField(default=0)),
            ],
            options={
                'db_table': 'name_bank_validation',
            },
        ),
        migrations.CreateModel(
            name='NameBankValidationHistory',
            fields=[
                ('cdate', models.DateTimeField(auto_now_add=True)),
                ('udate', models.DateTimeField(auto_now=True)),
                ('id', models.AutoField(db_column='name_bank_validation_history_id', primary_key=True, serialize=False)),
                ('event', models.CharField(max_length=50)),
                ('field_changes', django.contrib.postgres.fields.jsonb.JSONField()),
                ('name_bank_validation', models.ForeignKey(db_column='name_bank_validation_id', on_delete=django.db.models.deletion.DO_NOTHING, to='disbursement.NameBankValidation')),
            ],
            options={
                'db_table': 'name_bank_validation_history',
            },
        ),
        migrations.AddField(
            model_name='disbursement',
            name='name_bank_validation',
            field=models.ForeignKey(db_column='name_bank_validation_id', on_delete=django.db.models.deletion.CASCADE, to='disbursement.NameBankValidation'),
        ),
    ]
