# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2019-11-13 07:04
from __future__ import unicode_literals

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('followthemoney', '0032_add_withdrawal_feature_setting'),
    ]

    operations = [
        migrations.AddField(
            model_name='loanagreementtemplate',
            name='agreement_type',
            field=models.CharField(default='general', max_length=100),
        ),
        migrations.AlterField(
            model_name='loanagreementtemplate',
            name='lender',
            field=models.ForeignKey(blank=True, db_column='lender_id', null=True, on_delete=django.db.models.deletion.DO_NOTHING, to='followthemoney.LenderCurrent'),
        ),
    ]
