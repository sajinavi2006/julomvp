# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2022-10-24 06:40
from __future__ import unicode_literals

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.AlterField(
            model_name='emfinancingwfaccesstoken',
            name='form_type',
            field=models.CharField(choices=[('application', 'application'), ('disbursement', 'disbursement'), ('master_agreement', 'master_agreement')], max_length=50),
        ),
    ]
