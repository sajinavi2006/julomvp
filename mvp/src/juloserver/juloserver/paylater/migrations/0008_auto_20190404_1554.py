# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2019-04-04 08:54
from __future__ import unicode_literals

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('paylater', '0007_auto_20190404_1307'),
    ]

    operations = [
        migrations.AlterField(
            model_name='linesubscription',
            name='status',
            field=models.ForeignKey(db_column='status_code', on_delete=django.db.models.deletion.DO_NOTHING, to='julo.StatusLookup'),
        ),
    ]
