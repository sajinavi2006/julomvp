# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2022-08-30 03:20
from __future__ import unicode_literals

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.AddField(
            model_name='document',
            name='hash_digi_sign',
            field=models.CharField(blank=True, max_length=50, null=True),
        ),
    ]
