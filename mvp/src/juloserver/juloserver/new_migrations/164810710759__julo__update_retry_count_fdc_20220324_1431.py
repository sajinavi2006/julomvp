# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2022-03-24 07:31
from __future__ import unicode_literals

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.AlterField(
            model_name='fdcinquiry',
            name='retry_count',
            field=models.IntegerField(blank=True, default=None, null=True),
        ),
    ]
