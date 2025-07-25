# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2021-02-11 07:13
from __future__ import unicode_literals

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.AddField(
            model_name='partnerbankaccount',
            name='distributor_id',
            field=models.IntegerField(blank=True, null=True),
        ),
        migrations.AlterField(
            model_name='partnerbankaccount',
            name='partner',
            field=models.ForeignKey(db_column='partner_id', on_delete=django.db.models.deletion.DO_NOTHING, to='julo.Partner'),
        ),
    ]
