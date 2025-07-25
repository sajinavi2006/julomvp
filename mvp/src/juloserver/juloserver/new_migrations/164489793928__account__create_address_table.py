# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2022-02-15 04:05
from __future__ import unicode_literals

import django.core.validators
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.CreateModel(
            name='Address',
            fields=[
                ('cdate', models.DateTimeField(auto_now_add=True)),
                ('udate', models.DateTimeField(auto_now=True)),
                ('id', models.AutoField(db_column='address_id', primary_key=True, serialize=False)),
                ('latitude', models.FloatField(blank=True, null=True)),
                ('longitude', models.FloatField(blank=True, null=True)),
                ('provinsi', models.TextField()),
                ('kabupaten', models.TextField()),
                ('kecamatan', models.TextField()),
                ('kelurahan', models.TextField()),
                ('kodepos', models.CharField(blank=True, max_length=5, null=True, validators=[django.core.validators.RegexValidator(message='characters not allowed', regex='^[ -~]+$'), django.core.validators.RegexValidator(message='Kodepos harus 5 digit angka', regex='^[0-9]{5}$')])),
                ('detail', models.TextField()),
            ],
            options={
                'db_table': 'address',
            },
        ),
        migrations.AddField(
            model_name='account',
            name='credit_card_status',
            field=models.TextField(blank=True, null=True),
        ),
    ]
