# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2023-06-20 05:30
from __future__ import unicode_literals

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.CreateModel(
            name='PartnershipDistributor',
            fields=[
                ('cdate', models.DateTimeField(auto_now_add=True)),
                ('udate', models.DateTimeField(auto_now=True)),
                ('id', models.AutoField(db_column='partnership_distributor_id', primary_key=True, serialize=False)),
                ('distributor_id', models.BigIntegerField(db_index=True)),
                ('distributor_name', models.TextField(blank=True, null=True)),
                ('distributor_bank_account_number', models.TextField(blank=True, null=True, db_index=True)),
                ('distributor_bank_account_name', models.TextField(blank=True, null=True)),
                ('bank_code', models.TextField(blank=True, null=True)),
                ('bank_name', models.TextField(blank=True, null=True)),
                ('partner', models.ForeignKey(blank=True, db_column='partner_id', null=True, on_delete=django.db.models.deletion.DO_NOTHING, to='julo.Partner')),
            ],
            options={
                'db_table': 'partnership_distributor',
            },
        ),
    ]
