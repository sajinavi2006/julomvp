# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2023-02-28 10:50
from __future__ import unicode_literals

from django.db import migrations

from juloserver.julo.constants import WorkflowConst
from juloserver.julo.models import WorkflowStatusNode, Workflow


def run_me(apps, schema_editor):
    jstarWorkflow = Workflow.objects.get(name=WorkflowConst.JULO_STARTER)
    if WorkflowStatusNode.objects.filter(workflow=jstarWorkflow, status_node=106).exists():
        return

    WorkflowStatusNode.objects.create(
        workflow=jstarWorkflow, status_node=106, handler="JuloStarter106Handler"
    )


class Migration(migrations.Migration):
    dependencies = [
    ]

    operations = [
        migrations.RunPython(
            run_me,
            migrations.RunPython.noop
        )
    ]
