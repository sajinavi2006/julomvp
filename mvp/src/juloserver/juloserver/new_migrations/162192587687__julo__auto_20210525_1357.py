# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2021-05-25 06:57
from __future__ import unicode_literals

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.AddField(
            model_name='application',
            name='is_address_suspicious',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='applicationoriginal',
            name='is_address_suspicious',
            field=models.BooleanField(default=False),
        ),
    ]
