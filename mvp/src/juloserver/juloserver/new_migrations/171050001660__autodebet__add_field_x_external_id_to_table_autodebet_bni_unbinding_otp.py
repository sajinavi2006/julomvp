# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2024-03-15 10:53
from __future__ import unicode_literals

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.AddField(
            model_name='autodebetbniunbindingotp',
            name='x_external_id',
            field=models.CharField(blank=True, max_length=32, null=True),
        ),
    ]
