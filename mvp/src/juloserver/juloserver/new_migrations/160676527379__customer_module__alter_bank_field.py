# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2020-11-20 06:12
from __future__ import unicode_literals

from django.db import migrations, models
import django.db.models.deletion
from juloserver.customer_module.models import BankAccountDestination
from juloserver.julo.models import Bank, BankLookup


def retro_bank_name_data(_apps, _schema_editor):
    data_backup = BankAccountDestination.objects.raw(
        'SELECT bank_lookup_id, bank_account_destination_id FROM bank_account_destination')

    for data in data_backup:
        bank_lookup_id = data.bank_lookup_id
        bank_account_destination_id = data.id

        bank_lookup = BankLookup.objects.get(pk=bank_lookup_id)
        bank = Bank.objects.get(bank_name__iexact=bank_lookup.bank_name)

        BankAccountDestination.objects.filter(
            pk=bank_account_destination_id
        ).update(bank=bank)


class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.AddField(
            model_name='bankaccountdestination',
            name='bank_info',
            field=models.ForeignKey(
                db_column='bank_id', null=True,
                on_delete=django.db.models.deletion.DO_NOTHING, to='julo.Bank'),
        ),
        migrations.RunPython(retro_bank_name_data),
        migrations.RemoveField(
            model_name='bankaccountdestination',
            name='bank',
        ),
        migrations.RenameField(
            model_name='bankaccountdestination',
            old_name='bank_info',
            new_name='bank',
        ),
    ]
