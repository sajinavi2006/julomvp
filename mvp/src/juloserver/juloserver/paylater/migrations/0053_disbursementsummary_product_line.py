# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2019-10-01 06:35
from __future__ import unicode_literals

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('paylater', '0052_add_validator_initialcreditlimit'),
    ]

    operations = [
        migrations.AddField(
            model_name='disbursementsummary',
            name='product_line',
            field=models.OneToOneField(blank=True, db_column='product_line_id', null=True, on_delete=django.db.models.deletion.DO_NOTHING, to='julo.ProductLine'),
        ),
    ]
