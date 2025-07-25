# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2021-10-08 09:01
from __future__ import unicode_literals

from django.conf import settings
import django.core.validators
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.AlterField(
            model_name='masterpartnerconfigproductlookup',
            name='maximum_score',
            field=models.FloatField(help_text='Maximal value is 1', validators=[django.core.validators.MinValueValidator(0.01), django.core.validators.MaxValueValidator(1)]),
        ),
        migrations.AlterField(
            model_name='masterpartnerconfigproductlookup',
            name='minimum_score',
            field=models.FloatField(help_text='This value must be lower than maximum score', validators=[django.core.validators.MinValueValidator(0.01), django.core.validators.MaxValueValidator(1)]),
        ),
    ]
