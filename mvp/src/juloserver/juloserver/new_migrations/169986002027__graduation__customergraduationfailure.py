# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2023-11-13 07:20
from __future__ import unicode_literals

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.CreateModel(
            name='CustomerGraduationFailure',
            fields=[
                ('cdate', models.DateTimeField(auto_now_add=True)),
                ('udate', models.DateTimeField(auto_now=True)),
                ('id', models.AutoField(db_column='customer_graduation_failure_id', primary_key=True, serialize=False)),
                ('customer_graduation_id', models.IntegerField()),
                ('retries', models.IntegerField(default=0)),
                ('failure_reason', models.CharField(blank=True, max_length=255, null=True)),
                ('is_resolved', models.BooleanField(default=False)),
            ],
            options={
                'db_table': 'customer_graduation_failure',
            },
        ),
    ]
