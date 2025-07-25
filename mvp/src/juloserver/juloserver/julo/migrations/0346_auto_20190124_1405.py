# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2019-01-24 07:05
from __future__ import unicode_literals

import django.core.validators
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('julo', '0345_auto_20190131_1206'),
    ]

    operations = [
        migrations.AddField(
            model_name='application',
            name='birth_place',
            field=models.CharField(blank=True, max_length=100, null=True, validators=[django.core.validators.RegexValidator(message='characters not allowed', regex='^[ -~]+$')]),
        ),
        migrations.AddField(
            model_name='applicationoriginal',
            name='birth_place',
            field=models.CharField(blank=True, max_length=100, null=True, validators=[django.core.validators.RegexValidator(message='characters not allowed', regex='^[ -~]+$')]),
        ),
        migrations.AlterField(
            model_name='paymentexperiment',
            name='note_text',
            field=models.TextField(),
        ),
    ]
