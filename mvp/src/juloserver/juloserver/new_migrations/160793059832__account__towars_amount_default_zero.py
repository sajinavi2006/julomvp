# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2020-12-14 07:23
from __future__ import unicode_literals

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.AlterField(
            model_name='accounttransaction',
            name='towards_interest',
            field=models.BigIntegerField(default=0),
        ),
        migrations.AlterField(
            model_name='accounttransaction',
            name='towards_latefee',
            field=models.BigIntegerField(default=0),
        ),
        migrations.AlterField(
            model_name='accounttransaction',
            name='towards_principal',
            field=models.BigIntegerField(default=0),
        ),
    ]
