# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2023-04-03 15:01
from __future__ import unicode_literals

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.AlterField(
            model_name='axiatatemporarydata',
            name='partner_id',
            field=models.CharField(blank=True, default='', max_length=10, null=True),
        ),
    ]
