# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2024-09-16 07:50
from __future__ import unicode_literals

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.CreateModel(
            name='BalanceConsolidationDelinquentFDCChecking',
            fields=[
                ('cdate', models.DateTimeField(auto_now_add=True)),
                ('udate', models.DateTimeField(auto_now=True)),
                ('id', models.AutoField(db_column='balance_consolidation_delinquent_fdc_checking_id', primary_key=True, serialize=False)),
                ('customer_id', models.IntegerField()),
                ('invalid_fdc_inquiry_loan_id', models.IntegerField()),
                ('is_punishment_triggered', models.BooleanField(default=False)),
                ('balance_consolidation_verification', models.ForeignKey(db_column='balance_consolidation_verification_id', on_delete=django.db.models.deletion.DO_NOTHING, to='balance_consolidation.BalanceConsolidationVerification')),
            ],
            options={
                'db_table': 'balance_consolidation_delinquent_fdc_checking',
            },
        ),
    ]
