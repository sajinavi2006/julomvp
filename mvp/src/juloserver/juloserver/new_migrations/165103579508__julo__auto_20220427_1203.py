# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2022-04-27 05:03
from __future__ import unicode_literals

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.AlterField(
            model_name='partner',
            name='name',
            field=models.CharField(db_index=True, max_length=100),
        ),
    ]
