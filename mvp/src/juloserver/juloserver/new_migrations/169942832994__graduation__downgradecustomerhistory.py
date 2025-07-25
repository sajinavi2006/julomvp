# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2023-11-08 07:25
from __future__ import unicode_literals

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.CreateModel(
            name='DowngradeCustomerHistory',
            fields=[
                ('cdate', models.DateTimeField(auto_now_add=True)),
                ('udate', models.DateTimeField(auto_now=True)),
                ('id', models.AutoField(db_column='downgrade_customer_history_id', primary_key=True, serialize=False)),
                ('downgrade_type', models.CharField(blank=True, max_length=255, null=True)),
                ('latest_flag', models.BooleanField(default=False)),
                ('account', models.ForeignKey(db_column='account_id', on_delete=django.db.models.deletion.DO_NOTHING, to='account.Account')),
                ('available_limit_history', models.ForeignKey(db_column='available_limit_history_id', null=True, on_delete=django.db.models.deletion.DO_NOTHING, related_name='downgrade_available_limit_histories', to='account.AccountLimitHistory')),
                ('max_limit_history', models.ForeignKey(db_column='max_limit_history_id', null=True, on_delete=django.db.models.deletion.DO_NOTHING, related_name='downgrade_max_limit_histories', to='account.AccountLimitHistory')),
                ('set_limit_history', models.ForeignKey(db_column='set_limit_history_id', null=True, on_delete=django.db.models.deletion.DO_NOTHING, related_name='downgrade_set_limit_histories', to='account.AccountLimitHistory')),
            ],
            options={
                'db_table': 'downgrade_customer_history',
            },
        ),
    ]
