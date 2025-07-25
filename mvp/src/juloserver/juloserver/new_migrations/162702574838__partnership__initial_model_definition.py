# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2021-07-23 07:35
from __future__ import unicode_literals

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='Distributor',
            fields=[
                ('cdate', models.DateTimeField(auto_now_add=True)),
                ('udate', models.DateTimeField(auto_now=True)),
                ('id', models.AutoField(db_column='distributor_id', primary_key=True, serialize=False)),
                ('name', models.TextField()),
                ('address', models.TextField()),
                ('email', models.EmailField(max_length=254)),
                ('phone_number', models.TextField()),
                ('type_of_business', models.TextField()),
                ('npwp', models.TextField()),
                ('nib', models.TextField()),
                ('bank_account_name', models.TextField()),
                ('bank_account_number', models.TextField()),
                ('bank_name', models.TextField()),
            ],
            options={
                'db_table': 'distributor',
            },
        ),
        migrations.CreateModel(
            name='DistributorCategory',
            fields=[
                ('cdate', models.DateTimeField(auto_now_add=True)),
                ('udate', models.DateTimeField(auto_now=True)),
                ('id', models.AutoField(db_column='distributor_category_id', primary_key=True, serialize=False)),
                ('category_name', models.TextField()),
            ],
            options={
                'db_table': 'distributor_category',
            },
        ),
        migrations.CreateModel(
            name='MerchantHistoricalTransaction',
            fields=[
                ('cdate', models.DateTimeField(auto_now_add=True)),
                ('udate', models.DateTimeField(auto_now=True)),
                ('id', models.AutoField(db_column='merchant_historical_transaction_id', primary_key=True, serialize=False)),
                ('type', models.TextField()),
                ('transaction_date', models.DateField()),
                ('booking_date', models.DateField()),
                ('payment_method', models.TextField()),
                ('amount', models.BigIntegerField()),
                ('term_of_payment', models.BigIntegerField()),
                ('is_using_lending_facilities', models.BooleanField(default=False)),
                ('merchant', models.ForeignKey(db_column='merchant_id', on_delete=django.db.models.deletion.DO_NOTHING, to='merchant_financing.Merchant')),
            ],
            options={
                'db_table': 'merchant_historical_transaction',
            },
        ),
        migrations.CreateModel(
            name='PartnershipApiLog',
            fields=[
                ('cdate', models.DateTimeField(auto_now_add=True)),
                ('udate', models.DateTimeField(auto_now=True)),
                ('id', models.AutoField(db_column='partnership_api_log_id', primary_key=True, serialize=False)),
                ('api_type', models.TextField()),
                ('query_params', models.TextField(blank=True, null=True)),
                ('response', models.TextField(blank=True, null=True)),
                ('http_status_code', models.TextField(blank=True, null=True)),
                ('error_message', models.TextField(blank=True, null=True)),
                ('application', models.ForeignKey(blank=True, db_column='application_id', null=True, on_delete=django.db.models.deletion.DO_NOTHING, to='julo.Application')),
                ('customer', models.ForeignKey(blank=True, db_column='customer_id', null=True, on_delete=django.db.models.deletion.DO_NOTHING, to='julo.Customer')),
                ('distributor', models.ForeignKey(blank=True, db_column='distributor_id', null=True, on_delete=django.db.models.deletion.DO_NOTHING, to='partnership.Distributor')),
                ('partner', models.ForeignKey(db_column='partner_id', on_delete=django.db.models.deletion.DO_NOTHING, to='julo.Partner')),
            ],
            options={
                'db_table': 'partnership_api_log',
            },
        ),
        migrations.CreateModel(
            name='PartnershipConfig',
            fields=[
                ('cdate', models.DateTimeField(auto_now_add=True)),
                ('udate', models.DateTimeField(auto_now=True)),
                ('id', models.AutoField(db_column='partnership_config_id', primary_key=True, serialize=False)),
                ('partner_type', models.IntegerField()),
                ('partner', models.ForeignKey(db_column='partner_id', on_delete=django.db.models.deletion.DO_NOTHING, to='julo.Partner')),
            ],
            options={
                'db_table': 'partnership_config',
            },
        ),
        migrations.AddField(
            model_name='distributor',
            name='distributor_category',
            field=models.ForeignKey(db_column='distributor_category_id', on_delete=django.db.models.deletion.DO_NOTHING, to='partnership.DistributorCategory'),
        ),
        migrations.AddField(
            model_name='distributor',
            name='partner',
            field=models.ForeignKey(db_column='partner_id', on_delete=django.db.models.deletion.DO_NOTHING, to='julo.Partner'),
        ),
        migrations.AddField(
            model_name='distributor',
            name='user',
            field=models.OneToOneField(db_column='auth_user_id', on_delete=django.db.models.deletion.CASCADE, to=settings.AUTH_USER_MODEL),
        ),
    ]
