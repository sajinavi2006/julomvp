# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2020-10-30 12:31
from __future__ import unicode_literals

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.AlterField(
            model_name='accountproperty',
            name='voice_recording',
            field=models.BooleanField(default=True),
        ),
    ]
