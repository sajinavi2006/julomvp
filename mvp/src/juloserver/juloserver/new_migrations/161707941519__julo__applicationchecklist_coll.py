# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2021-03-30 04:43
from __future__ import unicode_literals

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.AddField(
            model_name='applicationchecklist',
            name='coll',
            field=models.NullBooleanField(),
        ),
    ]
