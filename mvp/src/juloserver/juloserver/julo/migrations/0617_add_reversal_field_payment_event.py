# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2020-02-25 05:10
from __future__ import unicode_literals

from django.conf import settings
import django.core.validators
from django.db import migrations, models
import django.db.models.deletion
import juloserver.julo.models


class Migration(migrations.Migration):

    dependencies = [
        ('julo', '0616_dasboardbucket_new_status_165'),
    ]

    operations = [
        migrations.AddField(
            model_name='paymentevent',
            name='reversal',
            field=models.IntegerField(blank=True, null=True),
        ),
    ]
