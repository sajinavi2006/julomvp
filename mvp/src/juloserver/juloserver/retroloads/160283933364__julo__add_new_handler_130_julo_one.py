# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2018-04-06 13:53
from __future__ import unicode_literals

from django.db import migrations

from juloserver.julo.models import WorkflowStatusPath, Workflow, WorkflowStatusNode


def add_status_path_130_to_141(apps, _schema_editor):

    workflow = Workflow.objects.filter(
        name="JuloOneWorkflow",
        is_active=True,
    ).last()
    WorkflowStatusPath.objects.get_or_create(
        status_previous=130,
        status_next=141,
        type="happy",
        workflow=workflow
    )
    WorkflowStatusPath.objects.get_or_create(
        status_previous=130,
        status_next=142,
        type="unhappy",
        workflow=workflow
    )
    WorkflowStatusNode.objects.get_or_create(
        status_node=130,
        handler='JuloOne130Handler',
        workflow=workflow
    )


class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.RunPython(add_status_path_130_to_141, migrations.RunPython.noop),
    ]
