# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2018-12-28 08:32
from __future__ import unicode_literals

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('julo', '0322_warningurl'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='warningurl',
            name='url_status',
        ),
        migrations.AddField(
            model_name='warningurl',
            name='is_enabled',
            field=models.BooleanField(default=True),
        ),
        migrations.AlterField(
            model_name='warningurl',
            name='id',
            field=models.AutoField(db_column='warning_url_id', primary_key=True, serialize=False),
        ),
    ]
