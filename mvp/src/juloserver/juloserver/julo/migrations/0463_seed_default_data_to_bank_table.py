from __future__ import unicode_literals

import django.contrib.auth.models
import django.core.validators
from django.db import migrations, models
import juloserver.julo.models

from juloserver.julo.banks import Banks

def add_default_value_bank_table(apps, schema_editor):
    Bank = apps.get_model("julo", "Bank")

    for bank in Banks:
        bank_data = Bank(bank_code=bank.bank_code,
                         bank_name=bank.bank_name,
                         min_account_number=bank.min_account_number,
                         xendit_bank_code=bank.xendit_bank_code,
                         instamoney_bank_code=bank.instamoney_bank_code,
                         xfers_bank_code=bank.xfers_bank_code,
                         swift_bank_code=bank.swift_bank_code)
        bank_data.save()

class Migration(migrations.Migration):
    initial = True

    dependencies = [
        ('julo', '0463_add_new_status_path_for_follow_the_money')
    ]

    operations = [
        migrations.RunPython(add_default_value_bank_table)
    ]
