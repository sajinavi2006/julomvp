# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2021-09-22 10:08
from __future__ import unicode_literals

from django.db import migrations

from juloserver.julo.constants import WorkflowConst
from juloserver.julo.models import Workflow, WorkflowStatusPath


def create_workflow_status_path_120_to_121_merchant_financing(apps, _schema_editor):
    workflow = Workflow.objects.get(name=WorkflowConst.MERCHANT_FINANCING_WORKFLOW)
    happy_path = WorkflowStatusPath.TYPE_CHOICES[0][0]
    WorkflowStatusPath.objects.get_or_create(
        status_previous=120,
        status_next=121,
        type=happy_path,
        workflow=workflow
    )


class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.RunPython(create_workflow_status_path_120_to_121_merchant_financing, migrations.RunPython.noop),
    ]
