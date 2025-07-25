# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2021-12-17 06:56
from __future__ import unicode_literals

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.CreateModel(
            name='MerchantApplicationReapplyInterval',
            fields=[
                ('cdate', models.DateTimeField(auto_now_add=True)),
                ('udate', models.DateTimeField(auto_now=True)),
                ('id', models.AutoField(db_column='merchant_application_reapply_interval_id', primary_key=True, serialize=False)),
                ('interval_day', models.PositiveIntegerField()),
                ('application_status', models.ForeignKey(db_column='status_code', on_delete=django.db.models.deletion.DO_NOTHING, to='julo.StatusLookup')),
                ('partner', models.ForeignKey(blank=True, db_column='partner_id', null=True, on_delete=django.db.models.deletion.DO_NOTHING, to='julo.Partner')),
            ],
            options={
                'abstract': False,
            },
        ),
    ]
