# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2020-07-23 10:07
from __future__ import unicode_literals

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('followthemoney', '0051_update_lla_template'),
    ]

    operations = [
        migrations.AddField(
            model_name='lenderrepaymenttransaction',
            name='repayment_type',
            field=models.CharField(max_length=100, null=True),
        ),
    ]
