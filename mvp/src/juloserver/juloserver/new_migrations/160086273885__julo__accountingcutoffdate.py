# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2020-09-23 12:05
from __future__ import unicode_literals

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.CreateModel(
            name='AccountingCutOffDate',
            fields=[
                ('cdate', models.DateTimeField(auto_now_add=True)),
                ('udate', models.DateTimeField(auto_now=True)),
                ('id', models.AutoField(db_column='accounting_cut_off_date_id', primary_key=True, serialize=False)),
                ('accounting_period', models.CharField(max_length=50)),
                ('cut_off_date', models.DateField(blank=True, null=True)),
                ('cut_off_date_last_change_ts', models.DateTimeField(blank=True, null=True)),
            ],
            options={
                'db_table': 'accounting_cut_off_date',
            },
        ),
    ]
