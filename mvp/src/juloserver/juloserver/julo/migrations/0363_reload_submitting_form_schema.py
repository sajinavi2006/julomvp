# -*- coding: utf-8 -*-
from __future__ import unicode_literals
from django.db import migrations
from ..management.commands import load_workflow


def reload_submitting_form_schema(apps, schema_editor):
    workflow_names = ('submitting_form',)
    for workflow_name in workflow_names:
        workflow_cmd = load_workflow.Command()
        opts = {'workflow_name': (workflow_name,)}
        workflow_cmd.handle(**opts)

class Migration(migrations.Migration):

    dependencies = [
        ('julo', '0362_add_last_installment_at_offer'),
    ]

    operations = [
        migrations.RunPython(reload_submitting_form_schema, migrations.RunPython.noop)
    ]
