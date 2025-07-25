# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2024-08-15 05:56
from __future__ import unicode_literals

from django.db import migrations
from juloserver.julo.models import Workflow, WorkflowStatusNode


def add_status_node_140(apps, _schema_editor):
    #
    # workflow = Workflow.objects.filter(name="CashLoanWorkflow").first()
    workflow = Workflow.objects.filter(
        name="JuloOneWorkflow",
        is_active=True,
    ).last()
    # WorkflowStatusPath

    if workflow:
        WorkflowStatusNode.objects.get_or_create(
            status_node=140,
            handler='JuloOne140Handler',
            workflow=workflow
        )


class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.RunPython(add_status_node_140, migrations.RunPython.noop),
    ]
