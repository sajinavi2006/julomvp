# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2020-09-22 08:26
from __future__ import unicode_literals

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.AddField(
            model_name='smshistory',
            name='category',
            field=models.CharField(blank=True, max_length=20, null=True),
        ),
    ]
