# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2023-11-20 07:25
from __future__ import unicode_literals

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.AddField(
            model_name='balanceconsolidation',
            name='loan_duration',
            field=models.IntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='balanceconsolidation',
            name='signature_image',
            field=models.ImageField(blank=True, null=True, upload_to=''),
        ),
    ]
