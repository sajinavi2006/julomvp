# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2023-10-05 07:34
from __future__ import unicode_literals

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.AddField(
            model_name='appsflyerlogs',
            name='appsflyer_customer_id',
            field=models.CharField(blank=True, max_length=50, null=True),
        ),
        migrations.AddField(
            model_name='customer',
            name='appsflyer_customer_id',
            field=models.CharField(blank=True, max_length=50, null=True),
        ),
    ]
