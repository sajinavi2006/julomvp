# -*- coding: utf-8 -*-
from __future__ import unicode_literals
from django.db import migrations
from ..management.commands import load_workflow, update_status_lookups, load_status_change_reasons


def new_status_path_bulk_disbursement(apps, schema_editor):
    opts = {'workflow_name': ('cash_loan',)}
    load_workflow.Command().handle(**opts)


class Migration(migrations.Migration):

    dependencies = [
        ('julo', '0541_add_column_app_status_in_skiptrace_history_centerix'),
    ]

    operations = [
        migrations.RunPython(new_status_path_bulk_disbursement),
    ]