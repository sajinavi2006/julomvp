# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2016-12-01 05:43
from __future__ import unicode_literals

from django.db import migrations, models
import juloserver.julo.models


class Migration(migrations.Migration):

    dependencies = [
        ('julo', '0009_auto_20161130_1424'),
    ]

    operations = [
        migrations.AddField(
            model_name='devicescrapeddata',
            name='file',
            field=models.FileField(blank=True, db_column='internal_path', null=True, upload_to=juloserver.julo.models.upload_to),
        ),
    ]
