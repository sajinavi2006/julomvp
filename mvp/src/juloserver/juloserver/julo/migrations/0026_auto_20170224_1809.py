# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2017-02-24 11:09
from __future__ import unicode_literals

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('julo', '0025_auto_20170217_0923'),
    ]

    operations = [
        migrations.AlterField(
            model_name='applicationhistory',
            name='change_reason',
            field=models.CharField(default='system_triggered', max_length=500),
        ),
    ]
