# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2020-01-31 04:29
from __future__ import unicode_literals

from django.conf import settings
import django.core.validators
from django.db import migrations, models
import django.db.models.deletion
import juloserver.julo.models


class Migration(migrations.Migration):

    dependencies = [
        ('julo', '0640_change_cootek_experiment_setting'),
    ]

    operations = [
        migrations.CreateModel(
            name='CUserFeedback',
            fields=[
                ('cdate', models.DateTimeField(auto_now_add=True)),
                ('udate', models.DateTimeField(auto_now=True)),
                ('id', models.AutoField(db_column='c_user_feedback_id', primary_key=True, serialize=False)),
                ('rating', models.IntegerField()),
                ('feedback', models.TextField(blank=True, null=True)),
            ],
            options={
                'db_table': 'c_user_feedback',
            },
        ),
        migrations.AddField(
            model_name='cuserfeedback',
            name='application',
            field=models.ForeignKey(db_column='application_id', on_delete=django.db.models.deletion.DO_NOTHING, to='julo.Application'),
        ),
    ]
