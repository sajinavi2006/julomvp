# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2021-05-05 05:23
from __future__ import unicode_literals

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.AddField(
            model_name='accounttransaction',
            name='device',
            field=models.ForeignKey(blank=True, db_column='device_id', null=True, on_delete=django.db.models.deletion.DO_NOTHING, to='julo.Device'),
        ),
    ]
