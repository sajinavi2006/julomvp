# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2023-02-01 09:21
from __future__ import unicode_literals

from django.db import migrations, models
import django.db.models.deletion
import juloserver.julocore.customized_psycopg2.models


class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.CreateModel(
            name='FraudVelocityModelResultsCheck',
            fields=[
                ('cdate', models.DateTimeField(auto_now_add=True)),
                ('udate', models.DateTimeField(auto_now=True)),
                ('id', juloserver.julocore.customized_psycopg2.models.BigAutoField(db_column='fraud_velocity_model_results_check_id', primary_key=True, serialize=False)),
                ('is_fraud', models.BooleanField()),
                ('similar_selfie_bg', models.NullBooleanField()),
                ('guided_selfie', models.NullBooleanField()),
                ('active_liveness_match', models.NullBooleanField()),
                ('fraudulent_payslip', models.NullBooleanField()),
                ('fraudulent_ktp', models.NullBooleanField()),
                ('invalid_phone_1', models.NullBooleanField()),
                ('invalid_phone_2', models.NullBooleanField()),
                ('invalid_kin_phone', models.NullBooleanField()),
                ('invalid_close_kin_phone', models.NullBooleanField()),
                ('invalid_spouse_phone', models.NullBooleanField()),
                ('invalid_company_phone', models.NullBooleanField()),
                ('sus_acc_from_phone_2', models.NullBooleanField()),
                ('sus_acc_from_kin_phone', models.NullBooleanField()),
                ('sus_acc_from_close_kin_phone', models.NullBooleanField()),
                ('sus_acc_from_spouse_phone', models.NullBooleanField()),
                ('address_suspicious', models.NullBooleanField()),
                ('job_detail_sus', models.NullBooleanField()),
                ('monthly_income_sus', models.NullBooleanField()),
                ('monthly_expense_sus', models.NullBooleanField()),
                ('loan_purpose_sus', models.NullBooleanField()),
                ('registration_time_taken_sus', models.NullBooleanField()),
                ('remarks', models.TextField(blank=True, null=True)),
            ],
            options={
                'db_table': 'fraud_velocity_model_results_check',
            },
        ),
        migrations.CreateModel(
            name='FraudVerificationResults',
            fields=[
                ('cdate', models.DateTimeField(auto_now_add=True)),
                ('udate', models.DateTimeField(auto_now=True)),
                ('id', juloserver.julocore.customized_psycopg2.models.BigAutoField(db_column='fraud_verification_result_id', primary_key=True, serialize=False)),
                ('geohash', models.TextField(blank=True, null=True)),
                ('bucket', models.TextField()),
                ('android_id', models.TextField(blank=True, null=True)),
                ('latitude', models.FloatField(blank=True, null=True)),
                ('longitude', models.FloatField(blank=True, null=True)),
                ('radius', models.FloatField(blank=True, null=True)),
                ('reason', models.TextField()),
                ('account_status_code', models.ForeignKey(blank=True, db_column='account_status_code', null=True, on_delete=django.db.models.deletion.DO_NOTHING, to='julo.StatusLookup')),
                ('application', juloserver.julocore.customized_psycopg2.models.BigForeignKey(db_column='application_id', on_delete=django.db.models.deletion.DO_NOTHING, to='julo.Application')),
            ],
            options={
                'db_table': 'fraud_verification_results',
            },
        ),
        migrations.AddField(
            model_name='fraudvelocitymodelresultscheck',
            name='fraud_verification_result',
            field=juloserver.julocore.customized_psycopg2.models.BigForeignKey(blank=True, db_column='fraud_verification_result_id', null=True, on_delete=django.db.models.deletion.DO_NOTHING, to='fraud_security.FraudVerificationResults'),
        ),
    ]
