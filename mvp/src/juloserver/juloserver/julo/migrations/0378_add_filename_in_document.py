# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2019-03-06 10:40
from __future__ import unicode_literals

from django.db import migrations, models
import juloserver.julo.models


class Migration(migrations.Migration):

    dependencies = [
        ('julo', '0377_add_phone_at_otp_request'),
    ]

    operations = [
        migrations.AddField(
            model_name='document',
            name='filename',
            field=models.CharField(blank=True, max_length=200, null=True),
        ),
    ]
