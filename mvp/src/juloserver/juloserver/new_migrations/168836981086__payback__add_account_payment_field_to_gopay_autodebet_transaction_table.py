# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2023-07-03 07:36
from __future__ import unicode_literals

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.AddField(
            model_name='gopayautodebettransaction',
            name='account_payment',
            field=models.ForeignKey(blank=True, db_column='account_payment', null=True, on_delete=django.db.models.deletion.DO_NOTHING, to='account_payment.AccountPayment')
        ),
        migrations.AddField(
            model_name='gopayautodebettransaction',
            name='forced_inactive_by_julo',
            field=models.BooleanField(default=False)
        )
    ]
