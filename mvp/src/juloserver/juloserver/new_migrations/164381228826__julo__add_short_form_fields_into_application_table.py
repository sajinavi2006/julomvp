# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2022-02-02 14:31
from __future__ import unicode_literals

import django.core.validators
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.AddField(
            model_name='application',
            name='address_detail',
            field=models.CharField(blank=True, max_length=100, null=True, validators=[django.core.validators.RegexValidator(message='characters not allowed', regex='^[ -~]+$')]),
        ),
        migrations.AddField(
            model_name='applicationoriginal',
            name='address_detail',
            field=models.CharField(blank=True, max_length=100, null=True, validators=[django.core.validators.RegexValidator(message='characters not allowed', regex='^[ -~]+$')]),
        ),
    ]
