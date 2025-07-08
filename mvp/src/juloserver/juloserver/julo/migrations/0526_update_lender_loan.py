from __future__ import unicode_literals
from django.db import migrations
from juloserver.followthemoney.management.commands import retroload_update_lender_loan


def run_retroload_update_lender_loan(apps, schema_editor):
    retroload_update_lender_loan.Command().handle()


class Migration(migrations.Migration):

    dependencies = [
        ('julo', '0525_add_lender_id_in_loan'),
    ]

    operations = [
        migrations.RunPython(run_retroload_update_lender_loan),
    ]
