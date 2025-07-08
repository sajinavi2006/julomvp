from __future__ import unicode_literals
from django.db import migrations
from juloserver.julo.management.commands import retroload_bca_va_for_axiata_and_icare


def run_retroload_bca_va_for_axiata_and_icare(apps, schema_editor):
    retroload_bca_va_for_axiata_and_icare.Command().handle()


class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.RunPython(run_retroload_bca_va_for_axiata_and_icare),
    ]