# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2019-04-06 08:29
from __future__ import unicode_literals

import django.contrib.postgres.fields.jsonb
from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone


class Migration(migrations.Migration):

    dependencies = [
        ('paylater', '0011_remove_linestatement_customer'),
    ]

    operations = [
        migrations.CreateModel(
            name='AccountCreditLimit',
            fields=[
                ('cdate', models.DateTimeField(auto_now_add=True)),
                ('udate', models.DateTimeField(auto_now=True)),
                ('id', models.AutoField(db_column='account_credit_limit_id', primary_key=True, serialize=False)),
                ('account_credit_limit', models.BigIntegerField(default=0)),
                ('available_credit_limit', models.BigIntegerField(default=0)),
                ('account_credit_active_date', models.DateTimeField(blank=True, null=True)),
                ('partner_id', models.BigIntegerField(blank=True, null=True)),
                ('account_credit_status_code', models.ForeignKey(db_column='status_code', on_delete=django.db.models.deletion.DO_NOTHING, to='julo.StatusLookup')),
            ],
            options={
                'db_table': 'account_credit_limit',
            },
        ),
        migrations.CreateModel(
            name='CustomerCreditLimit',
            fields=[
                ('cdate', models.DateTimeField(auto_now_add=True)),
                ('udate', models.DateTimeField(auto_now=True)),
                ('id', models.AutoField(db_column='customer_credit_limit_id', primary_key=True, serialize=False)),
                ('customer_credit_limit', models.BigIntegerField()),
                ('customer_credit_active_date', models.DateTimeField(blank=True, null=True)),
                ('credit_score', models.OneToOneField(db_column='credit_score_id', on_delete=django.db.models.deletion.DO_NOTHING, to='julo.CreditScore')),
                ('customer', models.OneToOneField(db_column='customer_id', on_delete=django.db.models.deletion.CASCADE, to='julo.Customer')),
                ('customer_credit_status_code', models.ForeignKey(db_column='status_code', on_delete=django.db.models.deletion.DO_NOTHING, to='julo.StatusLookup')),
            ],
            options={
                'db_table': 'customer_credit_limit',
            },
        ),
        migrations.CreateModel(
            name='Invoice',
            fields=[
                ('cdate', models.DateTimeField(auto_now_add=True)),
                ('udate', models.DateTimeField(auto_now=True)),
                ('id', models.AutoField(db_column='invoice_id', primary_key=True, serialize=False)),
                ('customer_xid', models.BigIntegerField()),
                ('invoice_number', models.CharField(max_length=100)),
                ('invoice_date', models.DateTimeField(blank=True, null=True)),
                ('invoice_amount', models.BigIntegerField()),
                ('invoice_due_date', models.DateField(blank=True, null=True)),
                ('transaction_fee_amount', models.BigIntegerField()),
                ('invoice_status', models.CharField(max_length=100)),
                ('account_credit_limit', models.ForeignKey(db_column='account_credit_limit_id', on_delete=django.db.models.deletion.DO_NOTHING, to='paylater.AccountCreditLimit')),
                ('customer_credit_limit', models.ForeignKey(db_column='customer_credit_limit_id', on_delete=django.db.models.deletion.CASCADE, to='paylater.CustomerCreditLimit')),
            ],
            options={
                'db_table': 'invoice',
            },
        ),
        migrations.CreateModel(
            name='InvoiceDetail',
            fields=[
                ('cdate', models.DateTimeField(auto_now_add=True)),
                ('udate', models.DateTimeField(auto_now=True)),
                ('id', models.AutoField(db_column='invoice_detail_id', primary_key=True, serialize=False)),
                ('partner_transaction_id', models.CharField(max_length=100)),
                ('shipping_address', models.TextField()),
                ('details', django.contrib.postgres.fields.jsonb.JSONField(blank=True, default=list, null=True)),
                ('partner_transaction_status', models.CharField(max_length=100)),
                ('invoice', models.ForeignKey(db_column='invoice_id', on_delete=django.db.models.deletion.DO_NOTHING, related_name='transactions', to='paylater.Invoice')),
            ],
            options={
                'db_table': 'invoice_detail',
            },
        ),
        migrations.CreateModel(
            name='LoanOne',
            fields=[
                ('cdate', models.DateTimeField(auto_now_add=True)),
                ('udate', models.DateTimeField(auto_now=True)),
                ('id', models.AutoField(db_column='loan_one_id', primary_key=True, serialize=False)),
                ('loan_amount', models.BigIntegerField(default=0)),
                ('loan_duration', models.IntegerField(default=1)),
                ('installment_amount', models.BigIntegerField(default=0)),
                ('partner_id', models.BigIntegerField(blank=True, null=True)),
                ('fund_transfer_ts', models.DateTimeField(blank=True, null=True)),
                ('customer', models.OneToOneField(db_column='customer_id', on_delete=django.db.models.deletion.CASCADE, to='julo.Customer')),
                ('loan_one_status_code', models.ForeignKey(db_column='status_code', on_delete=django.db.models.deletion.DO_NOTHING, to='julo.StatusLookup')),
            ],
            options={
                'db_table': 'loan_one',
            },
        ),
        migrations.CreateModel(
            name='PaymentSchedule',
            fields=[
                ('cdate', models.DateTimeField(auto_now_add=True)),
                ('udate', models.DateTimeField(auto_now=True)),
                ('id', models.AutoField(db_column='payment_schedule_id', primary_key=True, serialize=False)),
                ('due_date', models.DateField(blank=True, null=True)),
                ('due_amount', models.BigIntegerField()),
                ('interest_amount', models.BigIntegerField()),
                ('principal_amount', models.BigIntegerField()),
                ('transaction_fee_amount', models.BigIntegerField()),
                ('late_fee_amount', models.BigIntegerField(default=0)),
                ('late_fee_applied', models.IntegerField(default=0)),
                ('paid_date', models.DateField(blank=True, null=True)),
                ('paid_interest', models.BigIntegerField(default=0)),
                ('paid_principal', models.BigIntegerField(default=0)),
                ('paid_late_fee', models.BigIntegerField(default=0)),
                ('paid_transaction_fee', models.BigIntegerField(default=0)),
                ('paid_amount', models.BigIntegerField(default=0)),
                ('loan_one', models.ForeignKey(db_column='loan_one_id', on_delete=django.db.models.deletion.DO_NOTHING, to='paylater.LoanOne')),
            ],
            options={
                'db_table': 'payment_schedule',
            },
        ),
        migrations.CreateModel(
            name='Statement',
            fields=[
                ('cdate', models.DateTimeField(auto_now_add=True)),
                ('udate', models.DateTimeField(auto_now=True)),
                ('id', models.AutoField(db_column='statement_id', primary_key=True, serialize=False)),
                ('statement_due_date', models.DateField(blank=True, null=True)),
                ('statement_due_amount', models.BigIntegerField()),
                ('statement_interest_amount', models.BigIntegerField()),
                ('statement_principal_amount', models.BigIntegerField()),
                ('statement_transaction_fee_amount', models.BigIntegerField()),
                ('statement_late_fee_amount', models.BigIntegerField(default=0)),
                ('statement_late_fee_applied', models.IntegerField(default=0)),
                ('statement_paid_date', models.DateField(blank=True, null=True)),
                ('statement_paid_interest', models.BigIntegerField(default=0)),
                ('statement_paid_principal', models.BigIntegerField(default=0)),
                ('statement_paid_late_fee', models.BigIntegerField(default=0)),
                ('statement_paid_transaction_fee', models.BigIntegerField(default=0)),
                ('statement_paid_amount', models.BigIntegerField(default=0)),
                ('account_credit_limit', models.ForeignKey(db_column='account_credit_limit_id', on_delete=django.db.models.deletion.DO_NOTHING, to='paylater.AccountCreditLimit')),
                ('customer_credit_limit', models.ForeignKey(db_column='customer_credit_limit_id', on_delete=django.db.models.deletion.CASCADE, to='paylater.CustomerCreditLimit')),
                ('statement_status_code', models.ForeignKey(db_column='statement_status_code', on_delete=django.db.models.deletion.DO_NOTHING, to='julo.StatusLookup')),
            ],
            options={
                'db_table': 'statement',
            },
        ),
        migrations.CreateModel(
            name='TransactionOne',
            fields=[
                ('cdate', models.DateTimeField(auto_now_add=True)),
                ('udate', models.DateTimeField(auto_now=True)),
                ('id', models.AutoField(db_column='transaction_one_id', primary_key=True, serialize=False)),
                ('transaction_type', models.CharField(choices=[('Debit', 'debit'), ('Credit', 'credit')], max_length=100)),
                ('transaction_date', models.DateTimeField(default=django.utils.timezone.now)),
                ('transaction_amount', models.FloatField()),
                ('transaction_status', models.CharField(max_length=100)),
                ('transaction_description', models.TextField(blank=True, null=True)),
                ('disbursement_amount', models.BigIntegerField(default=0)),
                ('account_credit_limit', models.ForeignKey(db_column='account_credit_limit_id', on_delete=django.db.models.deletion.DO_NOTHING, to='paylater.AccountCreditLimit')),
                ('customer_credit_limit', models.ForeignKey(db_column='customer_credit_limit_id', on_delete=django.db.models.deletion.CASCADE, to='paylater.CustomerCreditLimit')),
                ('disbursement', models.ForeignKey(db_column='disbursement_id', on_delete=django.db.models.deletion.DO_NOTHING, to='disbursement.Disbursement')),
                ('invoice', models.ForeignKey(db_column='invoice_id', on_delete=django.db.models.deletion.DO_NOTHING, to='paylater.Invoice')),
                ('statement', models.ForeignKey(db_column='statement_id', on_delete=django.db.models.deletion.DO_NOTHING, to='paylater.Statement')),
            ],
            options={
                'db_table': 'transaction_one',
            },
        ),
        migrations.CreateModel(
            name='TransactionPaymentDetail',
            fields=[
                ('cdate', models.DateTimeField(auto_now_add=True)),
                ('udate', models.DateTimeField(auto_now=True)),
                ('id', models.AutoField(db_column='transaction_payment_id', primary_key=True, serialize=False)),
                ('payment_method_type', models.CharField(max_length=100)),
                ('payment_method_name', models.CharField(max_length=100)),
                ('payment_account_number', models.CharField(max_length=50)),
                ('payment_amount', models.BigIntegerField()),
                ('payment_date', models.DateField()),
                ('payment_ref', models.CharField(max_length=100)),
                ('transaction', models.OneToOneField(db_column='transaction_one_id', on_delete=django.db.models.deletion.DO_NOTHING, to='paylater.TransactionOne')),
            ],
            options={
                'db_table': 'transaction_payment_detail',
            },
        ),
        migrations.DeleteModel(
            name='Line',
        ),
        migrations.DeleteModel(
            name='LineDisbursement',
        ),
        migrations.DeleteModel(
            name='LineInvoice',
        ),
        migrations.DeleteModel(
            name='LineInvoiceDetail',
        ),
        migrations.DeleteModel(
            name='LineStatement',
        ),
        migrations.DeleteModel(
            name='LineSubscription',
        ),
        migrations.DeleteModel(
            name='LineTransaction',
        ),
        migrations.DeleteModel(
            name='LineTransactionPayment',
        ),
        migrations.AddField(
            model_name='paymentschedule',
            name='statement',
            field=models.ForeignKey(db_column='statement_id', on_delete=django.db.models.deletion.DO_NOTHING, to='paylater.Statement'),
        ),
        migrations.AddField(
            model_name='paymentschedule',
            name='status_code',
            field=models.ForeignKey(db_column='statement_status_code', on_delete=django.db.models.deletion.DO_NOTHING, to='julo.StatusLookup'),
        ),
        migrations.AddField(
            model_name='loanone',
            name='transaction',
            field=models.OneToOneField(db_column='transaction_one_id', on_delete=django.db.models.deletion.DO_NOTHING, to='paylater.TransactionOne'),
        ),
        migrations.AddField(
            model_name='accountcreditlimit',
            name='customer_credit_limit',
            field=models.ForeignKey(db_column='customer_credit_limit_id', on_delete=django.db.models.deletion.CASCADE, to='paylater.CustomerCreditLimit'),
        ),
    ]
