# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2023-05-31 06:53
from __future__ import unicode_literals

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.AddField(
            model_name='infocardproperty',
            name='youtube_video_id',
            field=models.CharField(max_length=100, null=True),
        ),
    ]
