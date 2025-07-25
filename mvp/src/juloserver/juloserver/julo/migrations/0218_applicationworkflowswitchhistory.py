# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2018-04-20 11:50
from __future__ import unicode_literals

import cuser.fields
from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('julo', '0217_auto_20180420_1530'),
    ]

    operations = [
        migrations.CreateModel(
            name='ApplicationWorkflowSwitchHistory',
            fields=[
                ('cdate', models.DateTimeField(auto_now_add=True)),
                ('udate', models.DateTimeField(auto_now=True)),
                ('id', models.AutoField(db_column='workflow_switch_history_id', primary_key=True, serialize=False)),
                ('workflow_old', models.CharField(max_length=200)),
                ('workflow_new', models.CharField(max_length=200)),
                ('change_reason', models.TextField(default='system_triggered')),
                ('application', models.ForeignKey(db_column='application_id', on_delete=django.db.models.deletion.DO_NOTHING, to='julo.Application')),
                ('changed_by', cuser.fields.CurrentUserField(editable=False, null=True, on_delete=django.db.models.deletion.CASCADE, to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'db_table': 'application_workflow_switch_history',
            },
        ),
    ]
