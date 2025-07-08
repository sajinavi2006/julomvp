# -*- coding: utf-8 -*-
from __future__ import unicode_literals
from django.db import migrations
from juloserver.julo.management.commands import load_workflow


def load_new_path_for_v3(apps, schema_editor):
    workflow_names = ('line_of_credit', 'cash_loan', 'grab_food', 'submitting_form')
    for workflow_name in workflow_names:
        workflow_cmd = load_workflow.Command()
        opts = {'workflow_name': (workflow_name,)}
        workflow_cmd.handle(**opts)

class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.RunPython(load_new_path_for_v3, migrations.RunPython.noop)
    ]
