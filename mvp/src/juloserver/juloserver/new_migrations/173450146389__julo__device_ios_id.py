# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2024-12-18 05:57
from __future__ import unicode_literals

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = []

    operations = [
        migrations.AddField(
            model_name='device',
            name='ios_id',
            field=models.TextField(blank=True, null=True),
        ),
    ]
