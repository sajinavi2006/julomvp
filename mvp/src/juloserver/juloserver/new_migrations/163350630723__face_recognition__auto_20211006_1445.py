# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2021-10-06 07:45
from __future__ import unicode_literals

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.AlterField(
            model_name='facerecommenderresult',
            name='face_search_result',
            field=models.ForeignKey(blank=True, db_column='face_search_result_id', null=True, on_delete=django.db.models.deletion.DO_NOTHING, to='face_recognition.FaceSearchResult'),
        ),
    ]
