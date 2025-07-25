# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2021-11-03 16:54
from __future__ import unicode_literals

from django.db import migrations, models
import django.db.models.deletion
import juloserver.julocore.customized_psycopg2.models


class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.CreateModel(
            name='SalesOpsAutodialerActivity',
            fields=[
                ('cdate', models.DateTimeField(auto_now_add=True)),
                ('udate', models.DateTimeField(auto_now=True)),
                ('id', juloserver.julocore.customized_psycopg2.models.BigAutoField(db_column='sales_ops_autodialer_activity_id', primary_key=True, serialize=False)),
                ('action', models.TextField()),
                ('phone_number', models.TextField(blank=True, null=True)),
                ('agent', models.ForeignKey(db_column='agent_id', on_delete=django.db.models.deletion.DO_NOTHING, to='julo.Agent')),
            ],
            options={
                'db_table': 'sales_ops_autodialer_activity',
            },
        ),
        migrations.CreateModel(
            name='SalesOpsAutodialerSession',
            fields=[
                ('cdate', models.DateTimeField(auto_now_add=True)),
                ('udate', models.DateTimeField(auto_now=True)),
                ('id', juloserver.julocore.customized_psycopg2.models.BigAutoField(db_column='sales_ops_autodialer_session_id', primary_key=True, serialize=False)),
                ('failed_count', models.PositiveIntegerField(default=0)),
                ('total_count', models.PositiveIntegerField(default=0)),
                ('next_session_ts', models.DateTimeField(blank=True, null=True)),
            ],
            options={
                'db_table': 'sales_ops_autodialer_session',
            },
        ),
        migrations.AddField(
            model_name='salesopsagentassignment',
            name='is_active',
            field=models.BooleanField(default=True),
        ),
        migrations.AddField(
            model_name='salesopsagentassignment',
            name='is_rpc',
            field=models.NullBooleanField(),
        ),
        migrations.AddField(
            model_name='salesopsagentassignment',
            name='non_rpc_attempt',
            field=models.PositiveIntegerField(blank=True, default=0),
        ),
        migrations.AddField(
            model_name='salesopslineup',
            name='latest_agent_assignment',
            field=models.OneToOneField(blank=True, db_column='latest_agent_assigment', null=True, on_delete=django.db.models.deletion.DO_NOTHING, to='sales_ops.SalesOpsAgentAssignment'),
        ),
        migrations.AddField(
            model_name='salesopsautodialersession',
            name='lineup',
            field=models.ForeignKey(db_column='lineup_id', on_delete=django.db.models.deletion.DO_NOTHING, to='sales_ops.SalesOpsLineup'),
        ),
        migrations.AddField(
            model_name='salesopsautodialeractivity',
            name='agent_assignment',
            field=models.ForeignKey(blank=True, db_column='sales_ops_agent_assignment_id', null=True, on_delete=django.db.models.deletion.DO_NOTHING, to='sales_ops.SalesOpsAgentAssignment'),
        ),
        migrations.AddField(
            model_name='salesopsautodialeractivity',
            name='autodialer_session',
            field=juloserver.julocore.customized_psycopg2.models.BigForeignKey(db_column='sales_ops_autodialer_session_id', on_delete=django.db.models.deletion.DO_NOTHING, to='sales_ops.SalesOpsAutodialerSession'),
        ),
        migrations.AddField(
            model_name='salesopsautodialeractivity',
            name='skiptrace_result_choice',
            field=models.ForeignKey(blank=True, db_column='skiptrace_result_choice_id', null=True, on_delete=django.db.models.deletion.DO_NOTHING, to='julo.SkiptraceResultChoice'),
        ),
    ]
