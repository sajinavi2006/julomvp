# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2022-03-11 02:32
from __future__ import unicode_literals

import django.core.validators
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.CreateModel(
            name='PartnershipLoanExpectation',
            fields=[
                ('cdate', models.DateTimeField(auto_now_add=True)),
                ('udate', models.DateTimeField(auto_now=True)),
                ('id', models.AutoField(db_column='partnership_loan_expectation_id', primary_key=True, serialize=False)),
                ('loan_amount_request', models.IntegerField(help_text='This value must be  between 1000000 and 20000000', validators=[django.core.validators.MinValueValidator(1000000), django.core.validators.MaxValueValidator(20000000)])),
                ('loan_duration_request', models.IntegerField(help_text='This value must be  between 1 and 12', validators=[django.core.validators.MinValueValidator(1), django.core.validators.MaxValueValidator(12)])),
                ('partnership_customer_data', models.ForeignKey(db_column='partnership_customer_data_id', on_delete=django.db.models.deletion.DO_NOTHING, to='partnership.PartnershipCustomerData')),
            ],
            options={
                'db_table': 'partnership_loan_expectation',
            },
        ),
    ]
