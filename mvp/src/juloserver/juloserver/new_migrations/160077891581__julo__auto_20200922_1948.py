# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2020-09-22 12:48
from __future__ import unicode_literals

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.AddField(
            model_name='emailhistory',
            name='category',
            field=models.CharField(blank=True, max_length=20, null=True),
        ),
        migrations.AddField(
            model_name='emailhistory',
            name='pre_header',
            field=models.CharField(blank=True, max_length=250, null=True),
        ),
    ]
