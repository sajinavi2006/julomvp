# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2021-02-24 09:19
from __future__ import unicode_literals

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.AlterField(
            model_name='ocrimagegvorcrequest',
            name='status',
            field=models.TextField(default=None, null=True),
        ),
        migrations.AlterField(
            model_name='ocrprocess',
            name='status',
            field=models.TextField(blank=True, default=None, null=True),
        ),
    ]
