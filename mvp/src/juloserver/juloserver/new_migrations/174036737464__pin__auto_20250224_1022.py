# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2025-02-24 03:22
from __future__ import unicode_literals

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = []

    operations = [
        migrations.AddField(
            model_name='customerpinchange',
            name='is_email_button_clicked',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='customerpinchange',
            name='is_form_button_clicked',
            field=models.BooleanField(default=False),
        ),
    ]
