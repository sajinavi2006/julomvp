# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2023-02-21 02:32
from __future__ import unicode_literals

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.AddField(
            model_name='danaloanreference',
            name='original_order_amount',
            field=models.BigIntegerField(default=None, null=True),
        ),
    ]
