# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2017-04-17 03:23
from __future__ import unicode_literals

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('julo', '0055_populate_application_to_customer'),
    ]

    operations = [
        migrations.AddField(
            model_name='application',
            name='application_number',
            field=models.IntegerField(blank=True, null=True),
        ),
    ]
