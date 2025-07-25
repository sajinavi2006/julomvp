# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2024-03-04 09:01
from __future__ import unicode_literals

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.AddField(
            model_name='channelingloanpayment',
            name='actual_interest_amount',
            field=models.BigIntegerField(blank=True, default=0),
        ),
        migrations.AddField(
            model_name='channelingloanpayment',
            name='risk_premium_amount',
            field=models.BigIntegerField(blank=True, default=0),
        ),
        migrations.AddField(
            model_name='channelingloanstatus',
            name='actual_interest_percentage',
            field=models.FloatField(blank=True, default=0, null=True),
        ),
        migrations.AddField(
            model_name='channelingloanstatus',
            name='risk_premium_percentage',
            field=models.FloatField(blank=True, default=0, null=True),
        ),
    ]
