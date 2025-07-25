# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2017-04-05 06:59
from __future__ import unicode_literals

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('julo', '0050_auto_20170405_0818'),
    ]

    operations = [
        migrations.CreateModel(
            name='DeviceGeolocation',
            fields=[
                ('cdate', models.DateTimeField(auto_now_add=True)),
                ('udate', models.DateTimeField(auto_now=True)),
                ('id', models.AutoField(db_column='device_geolocation_id', primary_key=True, serialize=False)),
                ('latitude', models.FloatField()),
                ('longitude', models.FloatField()),
                ('device', models.ForeignKey(db_column='device_id', on_delete=django.db.models.deletion.DO_NOTHING, to='julo.Device')),
            ],
            options={
                'db_table': 'device_geolocation',
            },
        ),
    ]
