# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2024-01-08 10:49
from __future__ import unicode_literals

from django.db import migrations, models
import juloserver.julocore.customized_psycopg2.models


class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.CreateModel(
            name='FDCPlatformCheckBypass',
            fields=[
                ('cdate', models.DateTimeField(auto_now_add=True)),
                ('udate', models.DateTimeField(auto_now=True)),
                ('id', juloserver.julocore.customized_psycopg2.models.BigAutoField(db_column='fdc_platform_check_bypass_id', primary_key=True, serialize=False)),
                ('application_id', models.BigIntegerField()),
            ],
            options={
                'db_table': '"ana"."fdc_platform_check_bypass"',
                'managed': False,
            },
        ),
    ]
