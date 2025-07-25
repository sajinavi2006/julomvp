# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2019-04-21 09:42
from __future__ import unicode_literals

import cuser.fields
from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('paylater', '0025_statementhistory'),
    ]

    operations = [
        migrations.CreateModel(
            name='AccountCreditHistory',
            fields=[
                ('cdate', models.DateTimeField(auto_now_add=True)),
                ('udate', models.DateTimeField(auto_now=True)),
                ('id', models.AutoField(db_column='account_credit_history_id', primary_key=True, serialize=False)),
                ('status_old', models.IntegerField()),
                ('status_new', models.IntegerField()),
                ('change_reason', models.TextField(default='system_triggered')),
                ('account_credit', models.ForeignKey(db_column='account_credit_limit_id', on_delete=django.db.models.deletion.DO_NOTHING, to='paylater.AccountCreditLimit')),
                ('changed_by', cuser.fields.CurrentUserField(editable=False, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='account_credit_status_changes', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'db_table': 'account_credit_history',
            },
        ),
    ]
