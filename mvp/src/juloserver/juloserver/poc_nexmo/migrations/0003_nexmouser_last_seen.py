# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2018-11-16 04:35
from __future__ import unicode_literals

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('poc_nexmo', '0002_nexmo_user'),
    ]

    operations = [
        migrations.AddField(
            model_name='nexmouser',
            name='last_seen',
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
