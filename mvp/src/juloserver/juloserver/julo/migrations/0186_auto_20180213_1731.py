# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2018-02-13 10:31
from __future__ import unicode_literals

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('julo', '0185_auto_20180202_1547'),
    ]

    operations = [
        migrations.AlterField(
            model_name='disbursement',
            name='loan',
            field=models.OneToOneField(db_column='loan_id', on_delete=django.db.models.deletion.DO_NOTHING, to='julo.Loan'),
        ),
    ]
