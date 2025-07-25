# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2023-04-03 10:21
from __future__ import unicode_literals

from django.db import migrations, models
import django.db.models.deletion
import juloserver.julocore.customized_psycopg2.models


class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.CreateModel(
            name='MonnaiInsightRawResult',
            fields=[
                ('cdate', models.DateTimeField(auto_now_add=True)),
                ('udate', models.DateTimeField(auto_now=True)),
                ('id', juloserver.julocore.customized_psycopg2.models.BigAutoField(db_column='monnai_insight_raw_result_id', primary_key=True, serialize=False)),
                ('raw', models.TextField()),
            ],
            options={
                'db_table': 'monnai_insight_raw_result',
            },
        ),
        migrations.CreateModel(
            name='MonnaiInsightRequest',
            fields=[
                ('cdate', models.DateTimeField(auto_now_add=True)),
                ('udate', models.DateTimeField(auto_now=True)),
                ('id', juloserver.julocore.customized_psycopg2.models.BigAutoField(db_column='monnai_insight_request_id', primary_key=True, serialize=False)),
                ('action_type', models.TextField(blank=True, null=True)),
                ('transaction_id', models.TextField(blank=True, null=True)),
                ('ip_address', models.TextField(blank=True, null=True)),
                ('phone_number', models.TextField(blank=True, null=True)),
                ('email_address', models.TextField(blank=True, null=True)),
                ('response_time', models.PositiveIntegerField(blank=True, null=True)),
                ('response_code', models.PositiveIntegerField(blank=True, null=True)),
                ('error_type', models.TextField(blank=True, null=True)),
                ('monnai_error_code', models.TextField(blank=True, null=True)),
                ('application', juloserver.julocore.customized_psycopg2.models.BigForeignKey(db_column='application_id', db_constraint=False, on_delete=django.db.models.deletion.DO_NOTHING, to='julo.Application')),
                ('customer', juloserver.julocore.customized_psycopg2.models.BigForeignKey(db_column='customer_id', db_constraint=False, on_delete=django.db.models.deletion.DO_NOTHING, to='julo.Customer')),
            ],
            options={
                'db_table': 'monnai_insight_request',
            },
        ),
        migrations.AddField(
            model_name='monnaiinsightrawresult',
            name='monnai_insight_request',
            field=juloserver.julocore.customized_psycopg2.models.BigOneToOneField(blank=True, db_column='monnai_insight_request_id', db_constraint=False, null=True, on_delete=django.db.models.deletion.DO_NOTHING, related_name='raw_result', to='fraud_score.MonnaiInsightRequest'),
        ),
    ]
