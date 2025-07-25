# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2020-10-20 09:59
from __future__ import unicode_literals

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    initial = True

    dependencies = [
    ]

    operations = [
        migrations.CreateModel(
            name='FDCDeliveryReport',
            fields=[
                ('cdate', models.DateTimeField(auto_now_add=True)),
                ('udate', models.DateTimeField(auto_now=True)),
                ('id', models.AutoField(db_column='fdc_delivery_report_id', primary_key=True, serialize=False)),
                ('generated_at', models.DateTimeField(blank=True, null=True)),
                ('last_reporting_loan', models.DateField(blank=True, null=True)),
                ('last_uploaded_sik', models.DateTimeField(blank=True, null=True)),
                ('last_uploaded_file_name', models.TextField(blank=True, null=True)),
                ('total_outstanding', models.IntegerField(blank=True, null=True)),
                ('total_paid_off', models.IntegerField(blank=True, null=True)),
                ('total_written_off', models.IntegerField(blank=True, null=True)),
                ('total_outstanding_outdated', models.IntegerField(blank=True, null=True)),
                ('percentage_updated', models.FloatField(blank=True, null=True)),
                ('threshold', models.FloatField(blank=True, null=True)),
                ('access_status', models.TextField(blank=True, null=True)),
            ],
            options={
                'db_table': 'fdc_delivery_report',
            },
        ),
        migrations.CreateModel(
            name='FDCOutdatedLoan',
            fields=[
                ('cdate', models.DateTimeField(auto_now_add=True)),
                ('udate', models.DateTimeField(auto_now=True)),
                ('id', models.AutoField(db_column='fdc_outdated_loan_id', primary_key=True, serialize=False)),
                ('report_date', models.DateField(blank=True, null=True)),
                ('reported_status', models.TextField(blank=True, null=True)),
                ('application', models.ForeignKey(db_column='application_id', on_delete=django.db.models.deletion.DO_NOTHING, to='julo.Application')),
                ('customer', models.ForeignKey(db_column='customer_id', on_delete=django.db.models.deletion.DO_NOTHING, to='julo.Customer')),
            ],
            options={
                'db_table': 'fdc_outdated_loan',
            },
        ),
    ]
