# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2023-08-21 05:35
from __future__ import unicode_literals

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.AddField(
            model_name='grabcustomerdata',
            name='is_customer_blocked_for_loan_creation',
            field=models.NullBooleanField(),
        ),
    ]
