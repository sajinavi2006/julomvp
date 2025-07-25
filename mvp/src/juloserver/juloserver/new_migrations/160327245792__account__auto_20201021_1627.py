# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2020-10-21 09:27
from __future__ import unicode_literals

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.AlterField(
            model_name='accounttransaction',
            name='disbursement',
            field=models.OneToOneField(blank=True, db_column='disbursement_id', null=True, on_delete=django.db.models.deletion.DO_NOTHING, to='disbursement.Disbursement'),
        ),
        migrations.AlterField(
            model_name='accounttransaction',
            name='payback_transaction',
            field=models.OneToOneField(blank=True, db_column='payback_transaction_id', null=True, on_delete=django.db.models.deletion.DO_NOTHING, to='julo.PaybackTransaction'),
        ),
    ]
