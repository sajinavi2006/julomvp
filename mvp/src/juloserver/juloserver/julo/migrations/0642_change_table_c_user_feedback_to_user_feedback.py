# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2020-02-03 09:00
from __future__ import unicode_literals

from django.conf import settings
import django.core.validators
from django.db import migrations, models
import django.db.models.deletion
import juloserver.julo.models


class Migration(migrations.Migration):

    dependencies = [
        ('julo', '0641_create_c_user_feedback_table'),
    ]

    operations = [
        migrations.CreateModel(
            name='UserFeedback',
            fields=[
                ('cdate', models.DateTimeField(auto_now_add=True)),
                ('udate', models.DateTimeField(auto_now=True)),
                ('id', models.AutoField(db_column='user_feedback_id', primary_key=True, serialize=False)),
                ('rating', models.IntegerField()),
                ('feedback', models.TextField(blank=True, null=True)),
            ],
            options={
                'db_table': 'user_feedback',
            },
        ),
        migrations.RemoveField(
            model_name='cuserfeedback',
            name='application',
        ),
        migrations.DeleteModel(
            name='CUserFeedback',
        ),
        migrations.AddField(
            model_name='userfeedback',
            name='application',
            field=models.ForeignKey(db_column='application_id', on_delete=django.db.models.deletion.DO_NOTHING, to='julo.Application'),
        ),
    ]
