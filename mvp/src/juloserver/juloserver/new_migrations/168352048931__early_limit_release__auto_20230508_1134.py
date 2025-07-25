# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2023-05-08 04:34
from __future__ import unicode_literals

import django.contrib.postgres.fields.jsonb
from django.db import migrations, models
import django.db.models.deletion
import juloserver.julocore.customized_psycopg2.models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
    ]

    operations = [
        migrations.CreateModel(
            name='EarlyReleaseChecking',
            fields=[
                ('cdate', models.DateTimeField(auto_now_add=True)),
                ('udate', models.DateTimeField(auto_now=True)),
                ('id', juloserver.julocore.customized_psycopg2.models.BigAutoField(db_column='checking_id', primary_key=True, serialize=False)),
                ('checking_type', models.CharField(choices=[('pre_requisite', 'Pre-requisite'), ('regular', 'Regular'), ('repeat', 'Repeat'), ('fdc', 'fdc'), ('used_limit', 'Used limit'), ('loan_duration', 'Loan duration')], max_length=255)),
                ('status', models.BooleanField(default=False)),
                ('reason', models.CharField(blank=True, max_length=255, null=True)),
                ('payment', juloserver.julocore.customized_psycopg2.models.BigForeignKey(db_column='payment_id', on_delete=django.db.models.deletion.DO_NOTHING, to='julo.Payment')),
            ],
            options={
                'db_table': 'early_release_checking',
            },
        ),
        migrations.CreateModel(
            name='EarlyReleaseExperiment',
            fields=[
                ('cdate', models.DateTimeField(auto_now_add=True)),
                ('udate', models.DateTimeField(auto_now=True)),
                ('id', models.AutoField(db_column='experiment_id', primary_key=True, serialize=False)),
                ('experiment_name', models.CharField(max_length=255)),
                ('option', models.CharField(max_length=255)),
                ('description', models.TextField(blank=True, null=True)),
                ('criteria', django.contrib.postgres.fields.jsonb.JSONField(default={})),
                ('is_active', models.BooleanField(default=False)),
                ('is_delete', models.BooleanField(default=False)),
            ],
            options={
                'db_table': 'early_release_experiment',
            },
        ),
        migrations.CreateModel(
            name='EarlyReleaseLoanMapping',
            fields=[
                ('cdate', models.DateTimeField(auto_now_add=True)),
                ('udate', models.DateTimeField(auto_now=True)),
                ('id', models.AutoField(db_column='loan_mapping_id', primary_key=True, serialize=False)),
                ('experiment', models.ForeignKey(db_column='experiment_id', on_delete=django.db.models.deletion.DO_NOTHING, to='early_limit_release.EarlyReleaseExperiment')),
                ('loan', juloserver.julocore.customized_psycopg2.models.BigForeignKey(db_column='loan_id', on_delete=django.db.models.deletion.DO_NOTHING, to='julo.Loan')),
            ],
            options={
                'db_table': 'early_release_loan_mapping',
            },
        ),
        migrations.CreateModel(
            name='ReleaseTracking',
            fields=[
                ('cdate', models.DateTimeField(auto_now_add=True)),
                ('udate', models.DateTimeField(auto_now=True)),
                ('id', juloserver.julocore.customized_psycopg2.models.BigAutoField(db_column='tracking_id', primary_key=True, serialize=False)),
                ('limit_release_amount', models.BigIntegerField()),
                ('account', models.ForeignKey(db_column='account_id', on_delete=django.db.models.deletion.DO_NOTHING, to='account.Account')),
                ('loan', juloserver.julocore.customized_psycopg2.models.BigForeignKey(db_column='loan_id', on_delete=django.db.models.deletion.DO_NOTHING, related_name='early_release_trackings', to='julo.Loan')),
                ('payment', juloserver.julocore.customized_psycopg2.models.BigForeignKey(db_column='payment_id', on_delete=django.db.models.deletion.DO_NOTHING, to='julo.Payment')),
            ],
            options={
                'db_table': 'early_release_tracking',
            },
        ),
        migrations.AlterUniqueTogether(
            name='earlyreleasechecking',
            unique_together=set([('payment', 'checking_type')]),
        ),
    ]
