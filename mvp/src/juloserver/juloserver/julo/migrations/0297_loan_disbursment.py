# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2018-10-18 09:04
from __future__ import unicode_literals

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('julo', '0297_auto_20181016_1151'),
    ]

    operations = [
        migrations.AddField(
            model_name='dashboardbuckets',
            name='app_164',
            field=models.IntegerField(default=0),
        ),
        migrations.AddField(
            model_name='loan',
            name='disbursement_id',
            field=models.BigIntegerField(blank=True, db_index=True, null=True),
        ),
        migrations.AddField(
            model_name='loan',
            name='name_bank_validation_id',
            field=models.BigIntegerField(blank=True, db_index=True, null=True),
        ),
    ]
