from __future__ import unicode_literals

from django.db import migrations


def add_bank_for_gopay(apps, schema_editor):
    Bank = apps.get_model("julo", "Bank")
    Bank.objects.get_or_create(
        bank_code='gopay',
        bank_name='GO-PAY',
        min_account_number=10,
        xendit_bank_code=None,
        instamoney_bank_code=None,
        xfers_bank_code=None,
        swift_bank_code=None,
    )


class Migration(migrations.Migration):

    dependencies = [
        ('disbursement', '0016_rename_new_disbursement_history'),
    ]

    operations = [
        migrations.RunPython(add_bank_for_gopay, migrations.RunPython.noop)
    ]