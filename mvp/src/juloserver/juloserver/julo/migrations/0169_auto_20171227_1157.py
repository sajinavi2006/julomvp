# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2017-12-27 04:57
from __future__ import unicode_literals

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('julo', '0168_auto_20171221_1502'),
    ]

    operations = [
        migrations.AlterField(
            model_name='disbursement',
            name='bank_number',
            field=models.CharField(blank=True, max_length=50, null=True),
        ),
    ]
