# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2021-01-23 07:06
from __future__ import unicode_literals

from django.db import migrations
from juloserver.julo.models import Workflow, WorkflowStatusPath
from juloserver.julo.constants import WorkflowConst

def add_workflow_axiata(apps, _schema_editor):

    workflow = Workflow.objects.create(
        name=WorkflowConst.MERCHANT_FINANCING_WORKFLOW,
        desc="this is a workflow for Merchant Financing",
        is_active=True,
        handler="MerchantFinancingWorkflowHandler"
    )
    # WorkflowStatusPath
    WorkflowStatusPath.objects.get_or_create(
        status_previous=0,
        status_next=190,
        type="happy",
        workflow=workflow
    )


class Migration(migrations.Migration):
    dependencies = [
    ]

    operations = [
        migrations.RunPython(add_workflow_axiata, migrations.RunPython.noop),
    ]

