# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2021-11-12 02:51
from __future__ import unicode_literals

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.CreateModel(
            name='AutodebetBenefitCounter',
            fields=[
                ('cdate', models.DateTimeField(auto_now_add=True)),
                ('udate', models.DateTimeField(auto_now=True)),
                ('id', models.AutoField(db_column='autodebet_benefit_counter_id', primary_key=True, serialize=False)),
                ('name', models.TextField()),
                ('counter', models.IntegerField(default=0)),
            ],
            options={
                'db_table': 'autodebet_benefit_counter',
            },
        ),
        migrations.RemoveField(
            model_name='autodebetbenefit',
            name='is_benefit_claimed',
        ),
        migrations.AddField(
            model_name='autodebetbenefit',
            name='benefit_config_value',
            field=models.TextField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='autodebetbenefit',
            name='payment',
            field=models.ForeignKey(blank=True, db_column='payment_id', null=True, on_delete=django.db.models.deletion.DO_NOTHING, to='julo.Payment'),
        ),
    ]
