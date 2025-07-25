# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2023-09-12 09:41
from __future__ import unicode_literals

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.CreateModel(
            name='FraudHighRiskAsn',
            fields=[
                ('cdate', models.DateTimeField(auto_now_add=True)),
                ('udate', models.DateTimeField(auto_now=True)),
                ('id', models.AutoField(db_column='high_risk_asn_id', primary_key=True, serialize=False)),
                ('name', models.CharField(max_length=255, unique=True)),
            ],
            options={
                'verbose_name_plural': 'High Risk ASN',
                'db_table': 'fraud_high_risk_asn',
            },
        ),
    ]
