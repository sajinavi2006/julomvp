# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2021-09-02 06:37
from __future__ import unicode_literals

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.AddField(
            model_name='bonzascoringresult',
            name='api_response',
            field=models.TextField(blank=True, null=True),
        ),
    ]
