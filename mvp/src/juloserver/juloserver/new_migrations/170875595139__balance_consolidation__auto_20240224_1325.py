# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2024-02-24 06:25
from __future__ import unicode_literals

import django.core.validators
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.AlterField(
            model_name='balanceconsolidationverification',
            name='validation_status',
            field=models.CharField(choices=[('draft', 'draft'), ('on_review', 'on_review'), ('approved', 'approved'), ('rejected', 'rejected'), ('abandoned', 'abandoned')], max_length=50, validators=[django.core.validators.RegexValidator(message='characters not allowed', regex='^[ -~]+$')]),
        ),
    ]
