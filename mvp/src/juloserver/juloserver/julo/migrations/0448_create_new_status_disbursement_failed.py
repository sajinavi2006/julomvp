# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import migrations
from ..management.commands import update_status_lookups


def create_new_status_disbursement_failed(apps, schema_editor):
    update_status_lookups.Command().handle()


class Migration(migrations.Migration):

    dependencies = [
        ('julo', '0448_alter_vendor_history_table_rename_column'),
    ]

    operations = [
        migrations.RunPython(create_new_status_disbursement_failed,
            migrations.RunPython.noop)
    ]
