# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2021-09-17 10:00
from __future__ import unicode_literals

import django.core.validators
from django.db import migrations, models
import django.db.models.deletion
import juloserver.julocore.customized_psycopg2.models


class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.CreateModel(
            name='HistoricalPartnerConfigProductLookup',
            fields=[
                ('cdate', models.DateTimeField(auto_now_add=True)),
                ('udate', models.DateTimeField(auto_now=True)),
                ('id', juloserver.julocore.customized_psycopg2.models.BigAutoField(db_column='historical_partner_config_product_lookup_id', primary_key=True, serialize=False)),
                ('minimum_score', models.FloatField(validators=[django.core.validators.MinValueValidator(0.1), django.core.validators.MaxValueValidator(1)])),
                ('maximum_score', models.FloatField(validators=[django.core.validators.MinValueValidator(0.1), django.core.validators.MaxValueValidator(1)])),
            ],
            options={
                'db_table': 'historical_partner_config_product_lookup',
            },
        ),
        migrations.CreateModel(
            name='MasterPartnerConfigProductLookup',
            fields=[
                ('cdate', models.DateTimeField(auto_now_add=True)),
                ('udate', models.DateTimeField(auto_now=True)),
                ('id', models.AutoField(db_column='master_partner_config_product_lookup_id', primary_key=True, serialize=False)),
                ('minimum_score', models.FloatField(validators=[django.core.validators.MinValueValidator(0.1), django.core.validators.MaxValueValidator(1)])),
                ('maximum_score', models.FloatField(validators=[django.core.validators.MinValueValidator(0.1), django.core.validators.MaxValueValidator(1)])),
                ('partner', models.ForeignKey(db_column='partner_id', on_delete=django.db.models.deletion.DO_NOTHING, to='julo.Partner')),
                ('product_lookup', models.ForeignKey(db_column='product_code', on_delete=django.db.models.deletion.DO_NOTHING, to='julo.ProductLookup')),
            ],
            options={
                'db_table': 'master_partner_config_product_lookup',
            },
        ),
        migrations.AddField(
            model_name='historicalpartnerconfigproductlookup',
            name='master_partner_config_product_lookup',
            field=models.ForeignKey(db_column='master_partner_config_product_lookup_id', on_delete=django.db.models.deletion.DO_NOTHING, to='partnership.MasterPartnerConfigProductLookup'),
        ),
        migrations.AddField(
            model_name='historicalpartnerconfigproductlookup',
            name='product_lookup',
            field=models.ForeignKey(db_column='product_code', on_delete=django.db.models.deletion.DO_NOTHING, to='julo.ProductLookup'),
        ),
    ]
