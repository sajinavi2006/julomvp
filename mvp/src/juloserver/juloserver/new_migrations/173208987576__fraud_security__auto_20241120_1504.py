# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2024-11-20 08:04
from __future__ import unicode_literals

import django.core.validators
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.CreateModel(
            name='FraudBlacklistedNIK',
            fields=[
                ('cdate', models.DateTimeField(auto_now_add=True)),
                ('udate', models.DateTimeField(auto_now=True)),
                ('id', models.AutoField(db_column='fraud_blacklisted_nik_id', primary_key=True, serialize=False)),
                ('nik', models.CharField(max_length=16, unique=True, validators=[django.core.validators.RegexValidator(message='characters not allowed', regex='^[ -~]+$'), django.core.validators.RegexValidator(message='NIK has to be 16 numeric digits', regex='^[0-9]{16}$')])),
                ('nik_tokenized', models.TextField(blank=True, null=True)),
            ],
            options={
                'db_table': 'fraud_blacklisted_nik',
            },
        ),
    ]
