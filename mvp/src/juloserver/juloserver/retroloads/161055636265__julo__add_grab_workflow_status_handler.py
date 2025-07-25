# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2020-09-22 09:24
from __future__ import unicode_literals

from django.db import migrations

from juloserver.julo.models import Workflow, WorkflowStatusPath, WorkflowStatusNode, ProductLine


def add_workflow_grab(apps, _schema_editor):

    workflow = Workflow.objects.filter(name='GrabWorkflow').last()
    # WorkflowStatusPath
    WorkflowStatusPath.objects.get_or_create(
        status_previous=0,
        status_next=100,
        type="happy",
        workflow=workflow
    )
    WorkflowStatusPath.objects.get_or_create(
        status_previous=100,
        status_next=105,
        type="happy",
        workflow=workflow
    )
    WorkflowStatusPath.objects.get_or_create(
        status_previous=105,
        status_next=135,
        type="unhappy",
        workflow=workflow
    )
    WorkflowStatusPath.objects.get_or_create(
        status_previous=105,
        status_next=120,
        type="happy",
        workflow=workflow
    )
    WorkflowStatusPath.objects.get_or_create(
        status_previous=105,
        status_next=106,
        type="unhappy",
        workflow=workflow
    )
    WorkflowStatusPath.objects.get_or_create(
        status_previous=120,
        status_next=121,
        type="happy",
        workflow=workflow
    )
    WorkflowStatusPath.objects.get_or_create(
        status_previous=120,
        status_next=123,
        type="unhappy",
        workflow=workflow
    )
    WorkflowStatusPath.objects.get_or_create(
        status_previous=120,
        status_next=125,
        type="unhappy",
        workflow=workflow
    )
    WorkflowStatusPath.objects.get_or_create(
        status_previous=120,
        status_next=131,
        type="unhappy",
        workflow=workflow
    )
    WorkflowStatusPath.objects.get_or_create(
        status_previous=121,
        status_next=124,
        type="happy",
        workflow=workflow
    )
    WorkflowStatusPath.objects.get_or_create(
        status_previous=121,
        status_next=137,
        type="happy",
        workflow=workflow
    )
    WorkflowStatusPath.objects.get_or_create(
        status_previous=124,
        status_next=130,
        type="happy",
        workflow=workflow
    )
    WorkflowStatusPath.objects.get_or_create(
        status_previous=125,
        status_next=121,
        type="happy",
        workflow=workflow
    )
    WorkflowStatusPath.objects.get_or_create(
        status_previous=121,
        status_next=135,
        type="graveyard",
        workflow=workflow
    )
    WorkflowStatusPath.objects.get_or_create(
        status_previous=130,
        status_next=141,
        type="happy",
        workflow=workflow
    )
    WorkflowStatusPath.objects.get_or_create(
        status_previous=124,
        status_next=135,
        type="unhappy",
        workflow=workflow
    )
    WorkflowStatusPath.objects.get_or_create(
        status_previous=141,
        status_next=150,
        type="happy",
        workflow=workflow
    )
    WorkflowStatusPath.objects.get_or_create(
        status_previous=147,
        status_next=150,
        type="unhappy",
        workflow=workflow
    )
    WorkflowStatusPath.objects.get_or_create(
        status_previous=150,
        status_next=147,
        type="detour",
        workflow=workflow
    )
    WorkflowStatusPath.objects.get_or_create(
        status_previous=150,
        status_next=135,
        type="graveyard",
        workflow=workflow
    )
    WorkflowStatusPath.objects.get_or_create(
        status_previous=150,
        status_next=145,
        type="graveyard",
        workflow=workflow
    )
    WorkflowStatusPath.objects.get_or_create(
        status_previous=150,
        status_next=190,
        type="happy",
        workflow=workflow
    )
    WorkflowStatusPath.objects.get_or_create(
        status_previous=131,
        status_next=132,
        type="detour",
        workflow=workflow
    )
    WorkflowStatusPath.objects.get_or_create(
        status_previous=145,
        status_next=150,
        type="happy",
        workflow=workflow
    )
    WorkflowStatusPath.objects.get_or_create(
        status_previous=121,
        status_next=131,
        type="detour",
        workflow=workflow
    )

    # WorkflowStatusNode
    WorkflowStatusNode.objects.create(
        status_node=105,
        handler='Grab105Handler',
        workflow=workflow
    )
    WorkflowStatusNode.objects.create(
        status_node=124,
        handler='Grab124Handler',
        workflow=workflow
    )
    WorkflowStatusNode.objects.create(
        status_node=130,
        handler='Grab130Handler',
        workflow=workflow
    )
    WorkflowStatusNode.objects.create(
        status_node=141,
        handler='Grab141Handler',
        workflow=workflow
    )
    WorkflowStatusNode.objects.create(
        status_node=150,
        handler='Grab150Handler',
        workflow=workflow
    )
    WorkflowStatusNode.objects.create(
        status_node=190,
        handler='Grab190Handler',
        workflow=workflow
    )


class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.RunPython(add_workflow_grab, migrations.RunPython.noop),
    ]
