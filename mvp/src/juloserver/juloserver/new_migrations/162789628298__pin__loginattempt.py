# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2021-08-02 09:24
from __future__ import unicode_literals

from django.db import migrations, models
import django.db.models.deletion
import juloserver.julocore.customized_psycopg2.models


class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.CreateModel(
            name='LoginAttempt',
            fields=[
                ('cdate', models.DateTimeField(auto_now_add=True)),
                ('udate', models.DateTimeField(auto_now=True)),
                ('id', models.AutoField(db_column='customer_login_id', primary_key=True, serialize=False)),
                ('android_id', models.CharField(max_length=50)),
                ('latitude', models.FloatField()),
                ('longitude', models.FloatField()),
                ('username', models.CharField(max_length=100)),
                ('is_fraud_hotspot', models.NullBooleanField()),
                ('customer', juloserver.julocore.customized_psycopg2.models.BigForeignKey(db_column='application_id', on_delete=django.db.models.deletion.DO_NOTHING, to='julo.Customer')),
                ('customer_pin_attempt', juloserver.julocore.customized_psycopg2.models.BigForeignKey(blank=True, db_column='customer_pin_attempt_id', null=True, on_delete=django.db.models.deletion.DO_NOTHING, to='pin.CustomerPinAttempt')),
            ],
            options={
                'db_table': 'login_attempt',
            },
        ),
    ]
