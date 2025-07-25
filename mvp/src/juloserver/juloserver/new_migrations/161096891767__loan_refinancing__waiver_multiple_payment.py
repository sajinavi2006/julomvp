# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2021-01-18 11:21
from __future__ import unicode_literals

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.AddField(
            model_name='loanrefinancingrequest',
            name='is_multiple_ptp_payment',
            field=models.NullBooleanField(default=False),
        ),
        migrations.AddField(
            model_name='waiverrequest',
            name='is_multiple_ptp_payment',
            field=models.NullBooleanField(default=False),
        ),
        migrations.AddField(
            model_name='waiverrequest',
            name='number_of_multiple_ptp_payment',
            field=models.IntegerField(blank=True, null=True),
        ),
    ]
