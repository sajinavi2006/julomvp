# -*- coding: utf-8 -*-
from __future__ import unicode_literals
from django.db import migrations
from juloserver.julo.management.commands import load_workflow, update_status_lookups, load_status_change_reasons


def new_cash_loan_163_handler(apps, schema_editor):
    opts = {'workflow_name': ('cash_loan',)}
    load_workflow.Command().handle(**opts)


class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.RunPython(new_cash_loan_163_handler)
    ]
