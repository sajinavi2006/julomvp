# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2022-01-24 07:09
from __future__ import unicode_literals

import django.core.validators
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.AddField(
            model_name='julovers',
            name='real_nik',
            field=models.CharField(blank=True, max_length=16, null=True, unique=True, validators=[django.core.validators.RegexValidator(message='characters not allowed', regex='^[ -~]+$'), django.core.validators.RegexValidator(message='KTP has to be 16 numeric digits', regex='^[0-9]{16}$')]),
        ),
    ]
