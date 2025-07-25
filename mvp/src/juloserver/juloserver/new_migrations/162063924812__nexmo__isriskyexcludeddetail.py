# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2021-05-10 09:34
from __future__ import unicode_literals

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.CreateModel(
            name='IsRiskyExcludedDetail',
            fields=[
                ('cdate', models.DateTimeField(auto_now_add=True)),
                ('udate', models.DateTimeField(auto_now=True)),
                ('id', models.AutoField(db_column='is_risky_excluded_detail_id', primary_key=True, serialize=False)),
                ('dpd', models.CharField(max_length=10)),
                ('model_version', models.CharField(blank=True, max_length=50, null=True)),
                ('account_payment', models.ForeignKey(blank=True, db_column='account_payment_id', null=True, on_delete=django.db.models.deletion.DO_NOTHING, to='account_payment.AccountPayment')),
                ('payment', models.ForeignKey(blank=True, db_column='payment_id', null=True, on_delete=django.db.models.deletion.DO_NOTHING, to='julo.Payment')),
            ],
            options={
                'db_table': 'is_risky_excluded_detail',
            },
        ),
    ]
