# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2024-07-30 04:38
from __future__ import unicode_literals

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = []

    operations = [
        migrations.AddField(
            model_name='fraudreport',
            name='email_tokenized',
            field=models.TextField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='fraudreport',
            name='nik_tokenized',
            field=models.TextField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='fraudreport',
            name='phone_number_tokenized',
            field=models.TextField(blank=True, null=True),
        ),
    ]
