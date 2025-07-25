# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2021-07-19 11:39
from __future__ import unicode_literals

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.AddField(
            model_name='otprequest',
            name='email',
            field=models.CharField(blank=True, max_length=255, null=True),
        ),
        migrations.AddField(
            model_name='otprequest',
            name='email_history',
            field=models.OneToOneField(blank=True, db_column='email_history_id', null=True, on_delete=django.db.models.deletion.DO_NOTHING, to='julo.EmailHistory'),
        ),
    ]
