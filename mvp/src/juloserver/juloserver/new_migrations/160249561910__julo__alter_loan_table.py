# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2020-10-12 09:40
from __future__ import unicode_literals

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.AddField(
            model_name='loan',
            name='account',
            field=models.ForeignKey(blank=True, db_column='account_id', null=True, on_delete=django.db.models.deletion.DO_NOTHING, to='account.Account'),
        ),
        migrations.AlterField(
            model_name='loan',
            name='offer',
            field=models.ForeignKey(blank=True, db_column='offer_id', null=True, on_delete=django.db.models.deletion.DO_NOTHING, to='julo.Offer'),
        ),
        migrations.AddField(
            model_name='loan',
            name='bank_account_destination',
            field=models.ForeignKey(blank=True, db_column='bank_account_destination_id', null=True,
                                    on_delete=django.db.models.deletion.DO_NOTHING,
                                    to='customer_module.BankAccountDestination'),
        ),
        migrations.AddField(
            model_name='loan',
            name='loan_xid',
            field=models.BigIntegerField(blank=True, null=True),
        ),
    ]
