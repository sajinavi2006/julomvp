# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2017-03-17 05:05
from __future__ import unicode_literals

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('julo', '0038_auto_20170319_2319'),
    ]

    operations = [
        migrations.AddField(
            model_name='application',
            name='college',
            field=models.CharField(blank=True, max_length=100, null=True),
        ),
        migrations.AddField(
            model_name='application',
            name='major',
            field=models.CharField(blank=True, max_length=100, null=True),
        ),
    ]
