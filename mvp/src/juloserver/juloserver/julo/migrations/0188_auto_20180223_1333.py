# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2018-02-23 06:33
from __future__ import unicode_literals

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('julo', '0187_init_lander'),
    ]

    operations = [
        migrations.AlterField(
            model_name='lenderbalanceevent',
            name='type',
            field=models.CharField(choices=[('deposit', 'deposit'), ('withdraw', 'withdraw')], max_length=50),
        ),
    ]
