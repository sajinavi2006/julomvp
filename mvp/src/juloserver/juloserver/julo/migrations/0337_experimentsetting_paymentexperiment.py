# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2019-01-18 11:19
from __future__ import unicode_literals

import django.contrib.postgres.fields.jsonb
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('julo', '0337_auto_20190118_1542'),
    ]

    operations = [
        migrations.CreateModel(
            name='ExperimentSetting',
            fields=[
                ('cdate', models.DateTimeField(auto_now_add=True)),
                ('udate', models.DateTimeField(auto_now=True)),
                ('id', models.AutoField(db_column='experiment_setting_id', primary_key=True, serialize=False)),
                ('code', models.CharField(max_length=50)),
                ('name', models.CharField(max_length=250)),
                ('start_date', models.DateTimeField()),
                ('end_date', models.DateTimeField()),
                ('schedule', models.CharField(max_length=10, blank=True, null=True)),
                ('action', models.CharField(max_length=100, blank=True, null=True)),
                ('type', models.CharField(max_length=50)),
                ('criteria', django.contrib.postgres.fields.jsonb.JSONField()),
                ('is_active', models.BooleanField(default=False)),
            ],
            options={
                'db_table': 'experiment_setting',
            },
        ),
        migrations.CreateModel(
            name='PaymentExperiment',
            fields=[
                ('cdate', models.DateTimeField(auto_now_add=True)),
                ('udate', models.DateTimeField(auto_now=True)),
                ('id', models.AutoField(db_column='payment_experiment_id', primary_key=True, serialize=False)),
                ('experiment_setting', models.ForeignKey(db_column='experiment_setting_id', on_delete=django.db.models.deletion.DO_NOTHING, to='julo.ExperimentSetting')),
                ('payment', models.ForeignKey(db_column='payment_id', on_delete=django.db.models.deletion.DO_NOTHING, to='julo.Payment')),
                ('note_text', models.TextField(db_column='note_text')),
            ],
            options={
                'db_table': 'payment_experiment',
            },
        ),
    ]
