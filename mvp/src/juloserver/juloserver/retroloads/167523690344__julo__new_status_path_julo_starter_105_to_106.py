# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2023-02-01 07:35
from __future__ import unicode_literals

from django.db import migrations
from juloserver.julo.models import Workflow, WorkflowStatusPath


def run_to_execute(apps, _schema_editor):

    workflow = Workflow.objects.get_or_none(name="JuloStarterWorkflow")
    if workflow:
        WorkflowStatusPath.objects.get_or_create(
            status_previous=100,
            status_next=106,
            type="detour",
            workflow=workflow
        )

        WorkflowStatusPath.objects.get_or_create(
            status_previous=105,
            status_next=106,
            type="detour",
            workflow=workflow
        )


class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.RunPython(run_to_execute, migrations.RunPython.noop)
    ]
