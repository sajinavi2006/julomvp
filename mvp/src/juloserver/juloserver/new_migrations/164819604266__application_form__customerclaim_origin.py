# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2022-03-25 08:14
from __future__ import unicode_literals

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.AddField(
            model_name='customerclaim',
            name='origin',
            field=models.CharField(blank=True, db_column='origin', max_length=50, null=True),
        ),
    ]
