# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2024-07-15 04:37
from __future__ import unicode_literals

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = []

    operations = [
        migrations.AddField(
            model_name='partnershipapplicationdata',
            name='risk_assessment_check',
            field=models.NullBooleanField(),
        ),
    ]
