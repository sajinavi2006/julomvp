# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2022-06-15 08:00
from __future__ import unicode_literals

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.AddField(
            model_name='paylatertransaction',
            name='partner',
            field=models.ForeignKey(db_column='partner_id', default=1000, on_delete=django.db.models.deletion.DO_NOTHING, to='julo.Partner'),
            preserve_default=False,
        ),
    ]
