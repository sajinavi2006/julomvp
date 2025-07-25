# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2019-06-13 04:28
from __future__ import unicode_literals

import cuser.fields
from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('paylater', '0040_statementnote')
    ]

    operations = [
        migrations.CreateModel(
            name='SkipTraceHistoryBl',
            fields=[
                ('cdate', models.DateTimeField(auto_now_add=True)),
                ('udate', models.DateTimeField(auto_now=True)),
                ('id', models.AutoField(db_column='skiptrace_history_bl_id', primary_key=True, serialize=False)),
                ('account_credit_limit', models.ForeignKey(db_column='account_credit_limit_id', on_delete=django.db.models.deletion.DO_NOTHING, to='paylater.AccountCreditLimit')),
                ('agent', cuser.fields.CurrentUserField(editable=False, null=True, on_delete=django.db.models.deletion.CASCADE, to=settings.AUTH_USER_MODEL)),
                ('call_result', models.ForeignKey(db_column='skiptrace_result_choice_id', on_delete=django.db.models.deletion.DO_NOTHING, to='julo.SkiptraceResultChoice')),
                ('skiptrace', models.ForeignKey(db_column='skiptrace_id', on_delete=django.db.models.deletion.DO_NOTHING, to='julo.Skiptrace')),
            ],
            options={
                'db_table': 'skiptrace_history_bl',
            },
        ),
    ]
