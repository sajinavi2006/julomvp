# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2024-04-21 14:08
from __future__ import unicode_literals

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = []

    operations = [
        migrations.AlterModelOptions(
            name='applicationdatacheck',
            options={'managed': False, 'ordering': ['application_id', 'sequence']},
        ),
    ]
