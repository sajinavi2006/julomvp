# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2021-02-10 00:58
from __future__ import unicode_literals

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.AlterField(
            model_name='axiatacustomerdata',
            name='application',
            field=models.ForeignKey(blank=True, db_column='application_id', null=True, on_delete=django.db.models.deletion.DO_NOTHING, to='julo.Application'),
        ),
    ]
