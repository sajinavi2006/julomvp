# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2018-02-02 08:47
from __future__ import unicode_literals

from django.db import migrations
from juloserver.paylater.constants import PaylaterConst


from juloserver.julo.models import PartnerBankAccount



from juloserver.julo.models import Partner



def create_bukalapak_bankaccount(apps, schema_editor):
    
    

    partner = Partner.objects.filter(name=PaylaterConst.PARTNER_NAME).last()
    if partner:
        BankAccount.objects.create(
            partner=partner,
            bank_name="BANK CENTRAL ASIA, Tbk (BCA)",
            bank_account_number="53243641321",
            name_in_bank="prod only",
            phone_number='+628111111111',
            distribution=100)


class Migration(migrations.Migration):
    dependencies = [
    ]

    operations = [
        migrations.RunPython(create_bukalapak_bankaccount, migrations.RunPython.noop)
    ]
