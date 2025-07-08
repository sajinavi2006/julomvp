from __future__ import unicode_literals

from django.db import migrations


from juloserver.julo.models import Bank



def add_bank_for_gopay(apps, schema_editor):
    
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
    ]

    operations = [
        migrations.RunPython(add_bank_for_gopay, migrations.RunPython.noop)
    ]