# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2020-10-20 06:15
from __future__ import unicode_literals

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.AddField(
            model_name='bankaccountcategory',
            name='display_label',
            field=models.TextField(default=1),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name='bankaccountdestination',
            name='description',
            field=models.TextField(blank=True, null=True),
        ),
    ]
