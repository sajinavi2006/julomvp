# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2019-02-21 15:42
from __future__ import unicode_literals

import django.core.validators
from django.db import migrations, models
import juloserver.julo.models


class Migration(migrations.Migration):

    dependencies = [
        ('julo', '0357_update_customer'),
    ]

    operations = [
        migrations.CreateModel(
            name='Document',
            fields=[
                ('cdate', models.DateTimeField(auto_now_add=True)),
                ('udate', models.DateTimeField(auto_now=True)),
                ('id', models.AutoField(db_column='document_id', primary_key=True, serialize=False)),
                ('document_source', models.BigIntegerField(db_column='document_source_id')),
                ('url', models.CharField(max_length=200)),
                ('service', models.CharField(choices=[('s3', 's3'), ('oss', 'oss')], default='oss', max_length=50)),
                ('document_type', models.CharField(max_length=50)),
            ],
            options={
                'db_table': 'document',
            },
        ),
    ]
