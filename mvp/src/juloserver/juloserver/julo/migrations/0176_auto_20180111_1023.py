# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2018-01-11 03:23
from __future__ import unicode_literals

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('julo', '0175_update_product_grab'),
    ]

    operations = [
        migrations.AddField(
            model_name='partnerreferral',
            name='product',
            field=models.ForeignKey(blank=True, db_column='product_code', null=True, on_delete=django.db.models.deletion.DO_NOTHING, to='julo.ProductLookup'),
        ),
        migrations.AlterField(
            model_name='partnerreferral',
            name='cust_email',
            field=models.EmailField(blank=True, max_length=254, null=True),
        ),
    ]
