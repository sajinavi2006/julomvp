# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2024-02-15 18:19
from __future__ import unicode_literals

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.AddField(
            model_name='danacustomerdata',
            name='full_name_tokenized',
            field=models.TextField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='danacustomerdata',
            name='mobile_number_tokenized',
            field=models.TextField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='danacustomerdata',
            name='nik_tokenized',
            field=models.TextField(blank=True, null=True),
        ),
    ]
