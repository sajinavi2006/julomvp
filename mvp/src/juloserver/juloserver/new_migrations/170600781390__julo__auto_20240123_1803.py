# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2024-01-23 11:03
from __future__ import unicode_literals

import django.core.validators
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.CreateModel(
            name='OtpLessHistory',
            fields=[
                ('cdate', models.DateTimeField(auto_now_add=True)),
                ('udate', models.DateTimeField(auto_now=True)),
                ('id', models.AutoField(db_column='otpless_history_id', primary_key=True, serialize=False)),
                ('status', models.CharField(default='sent', max_length=30)),
                ('otpless_reference_id', models.CharField(blank=True, max_length=50, null=True)),
                ('timestamp', models.DateTimeField(blank=True, null=True)),
                ('phone_number', models.CharField(blank=True, max_length=50, null=True, validators=[django.core.validators.RegexValidator(message='characters not allowed', regex='^[ -~]+$')])),
                ('channel', models.CharField(blank=True, max_length=50, null=True)),
            ],
            options={
                'db_table': 'otpless_history',
            },
        ),
        migrations.AddField(
            model_name='otprequest',
            name='otpless_reference_id',
            field=models.CharField(blank=True, max_length=50, null=True),
        ),
    ]
