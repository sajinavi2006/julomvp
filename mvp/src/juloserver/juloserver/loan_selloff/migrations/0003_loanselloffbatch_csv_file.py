# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2020-01-14 06:13
from __future__ import unicode_literals

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('loan_selloff', '0002_update_status_lookup'),
    ]

    operations = [
        migrations.AddField(
            model_name='loanselloffbatch',
            name='csv_file',
            field=models.TextField(blank=True, null=True),
        ),
    ]
