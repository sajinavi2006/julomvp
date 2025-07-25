# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2024-06-13 07:43
from __future__ import unicode_literals

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = []

    operations = [
        migrations.CreateModel(
            name='XfersProduct',
            fields=[
                ('cdate', models.DateTimeField(auto_now_add=True)),
                ('udate', models.DateTimeField(auto_now=True)),
                (
                    'id',
                    models.AutoField(
                        db_column='xfers_product_id', primary_key=True, serialize=False
                    ),
                ),
                ('product_id', models.CharField(blank=True, max_length=100, null=True)),
                ('product_name', models.CharField(blank=True, max_length=200, null=True)),
                ('product_nominal', models.BigIntegerField(blank=True, null=True)),
                ('type', models.CharField(blank=True, max_length=50, null=True)),
                ('category', models.CharField(blank=True, max_length=50, null=True)),
                ('partner_price', models.BigIntegerField(blank=True, null=True)),
                ('customer_price', models.BigIntegerField(blank=True, null=True)),
                ('is_active', models.BooleanField(default=False)),
                ('customer_price_regular', models.BigIntegerField(blank=True, null=True)),
                (
                    'sepulsa_product',
                    models.OneToOneField(
                        db_column='sepulsa_product_id',
                        on_delete=django.db.models.deletion.DO_NOTHING,
                        to='julo.SepulsaProduct',
                    ),
                ),
            ],
            options={
                'db_table': 'xfers_product',
            },
        ),
    ]
