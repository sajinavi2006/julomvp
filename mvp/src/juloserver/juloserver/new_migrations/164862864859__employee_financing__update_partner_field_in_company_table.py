# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2022-03-30 08:24
from __future__ import unicode_literals

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.AlterField(
            model_name='company',
            name='partner',
            field=models.ForeignKey(db_column='partner_id', on_delete=django.db.models.deletion.DO_NOTHING, to='julo.Partner'),
        ),
    ]
