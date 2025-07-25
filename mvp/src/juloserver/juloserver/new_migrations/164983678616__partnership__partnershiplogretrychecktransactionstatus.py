# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2022-04-13 07:59
from __future__ import unicode_literals

from django.db import migrations, models
import django.db.models.deletion
import juloserver.julocore.customized_psycopg2.models


class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.CreateModel(
            name='PartnershipLogRetryCheckTransactionStatus',
            fields=[
                ('cdate', models.DateTimeField(auto_now_add=True)),
                ('udate', models.DateTimeField(auto_now=True)),
                ('id', models.AutoField(db_column='partnership_log_retry_transaction_id', primary_key=True, serialize=False)),
                ('status', models.CharField(choices=[('in_progress', 'In Progress'), ('success', 'Success'), ('failed', 'Failed')], default='in_progress', max_length=20)),
                ('notes', models.CharField(blank=True, max_length=255, null=True)),
                ('loan', juloserver.julocore.customized_psycopg2.models.BigForeignKey(blank=True, db_column='loan_id', null=True, on_delete=django.db.models.deletion.DO_NOTHING, to='julo.Loan')),
                ('partnership_api_log', models.ForeignKey(blank=True, db_column='partnership_api_log_id', null=True, on_delete=django.db.models.deletion.DO_NOTHING, to='partnership.PartnershipApiLog')),
            ],
            options={
                'db_table': 'partner_log_retry_check_transaction_status',
            },
        ),
    ]
