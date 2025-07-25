# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2023-06-26 07:27
from __future__ import unicode_literals

from django.db import migrations, models
import juloserver.julocore.customized_psycopg2.models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
    ]

    operations = [
        migrations.CreateModel(
            name='ReferralBenefit',
            fields=[
                ('cdate', models.DateTimeField(auto_now_add=True)),
                ('udate', models.DateTimeField(auto_now=True)),
                ('id', juloserver.julocore.customized_psycopg2.models.BigAutoField(db_column='referral_benefit_id', primary_key=True, serialize=False)),
                ('benefit_type', models.CharField(choices=[('cashback', 'Cashback'), ('points', 'Points')], default='cashback', max_length=255)),
                ('referrer_benefit', models.PositiveIntegerField(default=0)),
                ('referee_benefit', models.PositiveIntegerField(default=0)),
                ('min_disburse_amount', models.PositiveIntegerField(default=0)),
                ('is_active', models.BooleanField(default=False)),
            ],
            options={
                'db_table': 'referral_benefit',
            },
        ),
        migrations.CreateModel(
            name='ReferralLevel',
            fields=[
                ('cdate', models.DateTimeField(auto_now_add=True)),
                ('udate', models.DateTimeField(auto_now=True)),
                ('id', juloserver.julocore.customized_psycopg2.models.BigAutoField(db_column='referral_level_id', primary_key=True, serialize=False)),
                ('benefit_type', models.CharField(choices=[('cashback', 'Cashback'), ('points', 'Points'), ('percentage', 'Percentage')], default='cashback', max_length=255)),
                ('referrer_level_benefit', models.PositiveIntegerField(default=0)),
                ('min_referees', models.PositiveIntegerField(default=0)),
                ('level', models.CharField(max_length=255)),
                ('is_active', models.BooleanField(default=False)),
            ],
            options={
                'db_table': 'referral_level',
            },
        ),
    ]
