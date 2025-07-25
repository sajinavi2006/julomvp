# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2021-05-25 06:57
from __future__ import unicode_literals

import django.contrib.postgres.fields.jsonb
from django.db import migrations, models
import django.db.models.deletion
import juloserver.julocore.customized_psycopg2.models


class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.CreateModel(
            name='ReverseGeolocation',
            fields=[
                ('cdate', models.DateTimeField(auto_now_add=True)),
                ('udate', models.DateTimeField(auto_now=True)),
                ('id', models.AutoField(db_column='reverse_geolocation_id', primary_key=True, serialize=False)),
                ('latitude', models.FloatField()),
                ('longitude', models.FloatField()),
                ('full_address', models.CharField(max_length=500)),
                ('response', django.contrib.postgres.fields.jsonb.JSONField(blank=True, default=None, null=True)),
                ('distance_km', models.FloatField()),
                ('application', juloserver.julocore.customized_psycopg2.models.BigForeignKey(db_column='application_id', on_delete=django.db.models.deletion.DO_NOTHING, to='julo.Application')),
                ('customer', juloserver.julocore.customized_psycopg2.models.BigForeignKey(db_column='customer_id', on_delete=django.db.models.deletion.DO_NOTHING, to='julo.Customer')),
                ('device_geolocation', models.ForeignKey(db_column='device_geolocation_id', on_delete=django.db.models.deletion.DO_NOTHING, to='julo.DeviceGeolocation')),
            ],
            options={
                'db_table': 'reverse_geolocation',
            },
        ),
    ]
