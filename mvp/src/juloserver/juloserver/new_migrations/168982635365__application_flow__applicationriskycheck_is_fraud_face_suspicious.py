# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2023-07-20 04:12
from __future__ import unicode_literals

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.AddField(
            model_name='applicationriskycheck',
            name='is_fraud_face_suspicious',
            field=models.NullBooleanField(),
        ),
    ]
