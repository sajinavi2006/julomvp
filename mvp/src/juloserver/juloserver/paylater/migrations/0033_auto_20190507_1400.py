# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2019-05-07 07:00
from __future__ import unicode_literals

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('paylater', '0032_initial_data_disbursementsummary'),
    ]

    operations = [
        migrations.CreateModel(
            name='BukalapakWhitelist',
            fields=[
                ('cdate', models.DateTimeField(auto_now_add=True)),
                ('udate', models.DateTimeField(auto_now=True)),
                ('id', models.AutoField(db_column='bukalapak_whitelist_id', primary_key=True, serialize=False)),
                ('email', models.EmailField(max_length=254, unique=True)),
                ('credit_limit', models.BigIntegerField(default=0)),
                ('probability_fpd', models.FloatField()),
            ],
            options={
                'db_table': 'bukalapak_whitelist',
            },
        ),
        migrations.AlterIndexTogether(
            name='bukalapakwhitelist',
            index_together=set([('email',)]),
        ),
    ]
