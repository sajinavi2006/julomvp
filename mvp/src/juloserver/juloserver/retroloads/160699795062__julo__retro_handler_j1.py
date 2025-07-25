# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2020-10-05 00:24
from __future__ import unicode_literals

from django.db import migrations

from juloserver.julo.models import Workflow, WorkflowStatusNode


def add_workflow_julo_one(apps, _schema_editor):

    workflow = Workflow.objects.get(
        name="JuloOneWorkflow"
    )
    # WorkflowStatusNode
    WorkflowStatusNode.objects.create(
        status_node=131,
        handler='JuloOne131Handler',
        workflow=workflow
    )
    WorkflowStatusNode.objects.create(
        status_node=133,
        handler='JuloOne133Handler',
        workflow=workflow
    )
    WorkflowStatusNode.objects.create(
        status_node=136,
        handler='JuloOne136Handler',
        workflow=workflow
    )
    WorkflowStatusNode.objects.create(
        status_node=137,
        handler='JuloOne137Handler',
        workflow=workflow
    )
    WorkflowStatusNode.objects.create(
        status_node=138,
        handler='JuloOne138Handler',
        workflow=workflow
    )
    WorkflowStatusNode.objects.create(
        status_node=139,
        handler='JuloOne139Handler',
        workflow=workflow
    )
    WorkflowStatusNode.objects.create(
        status_node=162,
        handler='JuloOne162Handler',
        workflow=workflow
    )
    WorkflowStatusNode.objects.create(
        status_node=172,
        handler='JuloOne172Handler',
        workflow=workflow
    )


class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.RunPython(add_workflow_julo_one, migrations.RunPython.noop)
    ]
