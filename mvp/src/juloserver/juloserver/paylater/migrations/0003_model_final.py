# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2019-04-03 09:18
from __future__ import unicode_literals

import django.contrib.postgres.fields.jsonb
from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone


class Migration(migrations.Migration):

    dependencies = [
        ('disbursement', '0005_auto_20190212_1217'),
        ('paylater', '0002_paylaterloan_paylaterstatement_paylatertransaction'),
    ]

    operations = [
        migrations.CreateModel(
            name='Line',
            fields=[
                ('cdate', models.DateTimeField(auto_now_add=True)),
                ('udate', models.DateTimeField(auto_now=True)),
                ('id', models.AutoField(db_column='line_id', primary_key=True, serialize=False)),
                ('limit', models.BigIntegerField()),
                ('status', models.CharField(default=b'inactive', max_length=100)),
                ('active_date', models.DateTimeField(blank=True, null=True)),
                ('type', models.CharField(max_length=100)),
                ('credit_score', models.TextField()),
                ('customer', models.OneToOneField(db_column='customer_id', on_delete=django.db.models.deletion.CASCADE, to='julo.Customer')),
            ],
            options={
                'db_table': 'line',
            },
        ),
        migrations.CreateModel(
            name='LineDisbursement',
            fields=[
                ('cdate', models.DateTimeField(auto_now_add=True)),
                ('udate', models.DateTimeField(auto_now=True)),
                ('id', models.AutoField(db_column='line_disbursement_id', primary_key=True, serialize=False)),
                ('amount', models.BigIntegerField()),
                ('disbursement', models.ForeignKey(db_column='disbursement_id', on_delete=django.db.models.deletion.DO_NOTHING, to='disbursement.Disbursement')),
            ],
            options={
                'db_table': 'line_disbursement',
            },
        ),
        migrations.CreateModel(
            name='LineInvoice',
            fields=[
                ('cdate', models.DateTimeField(auto_now_add=True)),
                ('udate', models.DateTimeField(auto_now=True)),
                ('id', models.AutoField(db_column='line_invoice_id', primary_key=True, serialize=False)),
                ('customer_xid', models.BigIntegerField()),
                ('invoice_number', models.CharField(max_length=100)),
                ('invoice_date', models.DateTimeField(blank=True, null=True)),
                ('invoice_amount', models.BigIntegerField()),
                ('due_date', models.DateField(blank=True, null=True)),
                ('admin_fee_amount', models.BigIntegerField()),
                ('status', models.CharField(max_length=100)),
                ('customer', models.OneToOneField(db_column='customer_id', on_delete=django.db.models.deletion.CASCADE, to='julo.Customer')),
            ],
            options={
                'db_table': 'line_invoice',
            },
        ),
        migrations.CreateModel(
            name='LineInvoiceDetail',
            fields=[
                ('cdate', models.DateTimeField(auto_now_add=True)),
                ('udate', models.DateTimeField(auto_now=True)),
                ('id', models.AutoField(db_column='line_invoice_detail_id', primary_key=True, serialize=False)),
                ('ext_transaction_id', models.CharField(max_length=100)),
                ('invoice_amount', models.BigIntegerField()),
                ('shipping_address', models.TextField()),
                ('items', django.contrib.postgres.fields.jsonb.JSONField(blank=True, null=True)),
                ('status', models.CharField(max_length=100)),
                ('line_invoice', models.ForeignKey(db_column='line_invoice_id', on_delete=django.db.models.deletion.DO_NOTHING, to='paylater.LineInvoice')),
            ],
            options={
                'db_table': 'line_invoice_detail',
            },
        ),
        migrations.CreateModel(
            name='LineStatement',
            fields=[
                ('cdate', models.DateTimeField(auto_now_add=True)),
                ('udate', models.DateTimeField(auto_now=True)),
                ('id', models.AutoField(db_column='line_statement_id', primary_key=True, serialize=False)),
                ('due_date', models.DateField(blank=True, null=True)),
                ('paid_date', models.DateField(blank=True, null=True)),
                ('subscription_fee_amount', models.BigIntegerField()),
                ('late_fee_amount', models.BigIntegerField()),
                ('status', models.CharField(max_length=100)),
                ('line', models.ForeignKey(db_column='line_id', on_delete=django.db.models.deletion.DO_NOTHING, to='paylater.Line')),
            ],
            options={
                'db_table': 'line_statement',
            },
        ),
        migrations.CreateModel(
            name='LineSubscription',
            fields=[
                ('cdate', models.DateTimeField(auto_now_add=True)),
                ('udate', models.DateTimeField(auto_now=True)),
                ('id', models.AutoField(db_column='line_subscription_id', primary_key=True, serialize=False)),
                ('limit', models.BigIntegerField()),
                ('available_limit', models.BigIntegerField()),
                ('status', models.CharField(default=b'inactive', max_length=100)),
                ('active_date', models.DateTimeField(blank=True, null=True)),
                ('type', models.CharField(max_length=100)),
                ('interest_rate', models.FloatField()),
                ('subscription_fee', models.BigIntegerField()),
                ('admin_fee', models.BigIntegerField()),
                ('line', models.ForeignKey(db_column='line_id', on_delete=django.db.models.deletion.CASCADE, to='paylater.Line')),
            ],
            options={
                'db_table': 'line_subscription',
            },
        ),
        migrations.CreateModel(
            name='LineTransaction',
            fields=[
                ('cdate', models.DateTimeField(auto_now_add=True)),
                ('udate', models.DateTimeField(auto_now=True)),
                ('id', models.AutoField(db_column='line_transaction_id', primary_key=True, serialize=False)),
                ('type', models.CharField(max_length=100)),
                ('transaction_date', models.DateTimeField(default=django.utils.timezone.now)),
                ('amount', models.FloatField()),
                ('credit', models.BooleanField()),
                ('debt', models.BooleanField()),
                ('status', models.CharField(max_length=100)),
                ('description', models.TextField(blank=True, null=True)),
                ('line_invoice', models.ForeignKey(db_column='line_invoice_id', on_delete=django.db.models.deletion.DO_NOTHING, to='paylater.LineInvoice')),
                ('line_statement', models.ForeignKey(db_column='line_statement_id', on_delete=django.db.models.deletion.DO_NOTHING, to='paylater.LineStatement')),
                ('line_subscription', models.ForeignKey(db_column='line_subscription_id', on_delete=django.db.models.deletion.DO_NOTHING, to='paylater.LineSubscription')),
            ],
            options={
                'db_table': 'line_transaction',
            },
        ),
        migrations.RemoveField(
            model_name='paylaterloan',
            name='customer',
        ),
        migrations.RemoveField(
            model_name='paylaterstatement',
            name='paylater_loan',
        ),
        migrations.RemoveField(
            model_name='paylatertransaction',
            name='paylater_loan',
        ),
        migrations.RemoveField(
            model_name='paylatertransaction',
            name='paylater_statement',
        ),
        migrations.DeleteModel(
            name='PaylaterLoan',
        ),
        migrations.DeleteModel(
            name='PaylaterStatement',
        ),
        migrations.DeleteModel(
            name='PaylaterTransaction',
        ),
        migrations.AddField(
            model_name='lineinvoice',
            name='line_subscription',
            field=models.ForeignKey(db_column='line_subscription_id', on_delete=django.db.models.deletion.DO_NOTHING, to='paylater.LineSubscription'),
        ),
        migrations.AddField(
            model_name='linedisbursement',
            name='line_transaction',
            field=models.ForeignKey(db_column='line_transaction_id', on_delete=django.db.models.deletion.DO_NOTHING, to='paylater.LineTransaction'),
        ),
    ]
