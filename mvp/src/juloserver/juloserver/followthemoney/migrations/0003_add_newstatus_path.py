# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import migrations


def add_new_status_path_for_followthemoney(apps, _schema_editor):
    """
    Add status path (165->135) reject application
    """
    Workflow = apps.get_model("julo", "Workflow")
    workflow = Workflow.objects.filter(name="CashLoanWorkflow").first()
    if workflow:
        WorkflowStatusPath = apps.get_model("julo", "WorkflowStatusPath")
        WorkflowStatusPath.objects.get_or_create(
            status_previous=165,
            status_next=135,
            type="detour",
            workflow=workflow
        )


class Migration(migrations.Migration):

    dependencies = [
        ('followthemoney', '0002_lenderbucket_total_loan_amount'),
    ]

    operations = [
        migrations.RunPython(add_new_status_path_for_followthemoney, migrations.RunPython.noop)
    ]
