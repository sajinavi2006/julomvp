# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2021-10-15 01:37
from __future__ import unicode_literals

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.AlterField(
            model_name='loan',
            name='loan_xid',
            field=models.BigIntegerField(blank=True, db_index=True, null=True),
        ),
    ]
