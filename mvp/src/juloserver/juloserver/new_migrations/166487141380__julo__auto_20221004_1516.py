# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2022-10-04 08:16
from __future__ import unicode_literals

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.AddField(
            model_name='partner',
            name='name_bank_validation',
            field=models.ForeignKey(blank=True, db_column='name_bank_validation_id', null=True, on_delete=django.db.models.deletion.DO_NOTHING, to='disbursement.NameBankValidation'),
        ),
        migrations.AddField(
            model_name='partner',
            name='partner_bank_account_name',
            field=models.CharField(blank=True, help_text='Please add partner bank account name if the disbursement needs to done on partner bank account', max_length=255, null=True),
        ),
        migrations.AddField(
            model_name='partner',
            name='partner_bank_name',
            field=models.CharField(blank=True, max_length=255, null=True),
        ),
    ]
