# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2023-01-03 07:05
from __future__ import unicode_literals

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.CreateModel(
            name='GraduationCustomerHistory',
            fields=[
                ('cdate', models.DateTimeField(auto_now_add=True)),
                ('udate', models.DateTimeField(auto_now=True)),
                ('id', models.AutoField(primary_key=True, serialize=False)),
                ('graduation_type', models.CharField(blank=True, max_length=255, null=True)),
                ('latest_flag', models.BooleanField(default=False)),
                ('account', models.ForeignKey(db_column='account_id', on_delete=django.db.models.deletion.DO_NOTHING, to='account.Account')),
                ('account_limit_history', models.ForeignKey(db_column='account_limit_history_id', on_delete=django.db.models.deletion.DO_NOTHING, to='account.AccountLimitHistory')),
            ],
            options={
                'db_table': 'graduation_customer_history',
            },
        ),
    ]
