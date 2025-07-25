# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2024-09-05 11:07
from __future__ import unicode_literals

from django.db import migrations

from juloserver.julo.constants import WorkflowConst, FeatureNameConst
from juloserver.julo.models import (
    WorkflowStatusPath,
    Workflow,
    WorkflowStatusNode,
    StatusLookup,
    FeatureSetting,
)
from juloserver.julo.statuses import ApplicationStatusCodes


def run(apps, _schema_editor):
    if not StatusLookup.objects.filter(status_code=ApplicationStatusCodes.BANK_NAME_CORRECTED).exists():
        StatusLookup.objects.create(
            status_code=ApplicationStatusCodes.BANK_NAME_CORRECTED,
            status="Bank Name Corrected",
        )

    workflow = Workflow.objects.filter(name=WorkflowConst.JULO_ONE).last()

    if not WorkflowStatusNode.objects.filter(
        status_node=ApplicationStatusCodes.BANK_NAME_CORRECTED,
        handler="JuloOne179Handler",
        workflow=workflow,
    ).exists():
        WorkflowStatusNode.objects.create(
            status_node=ApplicationStatusCodes.BANK_NAME_CORRECTED,
            handler="JuloOne179Handler",
            workflow=workflow,
        )

    paths = [
        (ApplicationStatusCodes.NAME_VALIDATE_FAILED, ApplicationStatusCodes.BANK_NAME_CORRECTED, "detour"),
        (ApplicationStatusCodes.BANK_NAME_CORRECTED, ApplicationStatusCodes.LOC_APPROVED, "happy"),
        (
            ApplicationStatusCodes.BANK_NAME_CORRECTED,
            ApplicationStatusCodes.APPLICATION_FLAGGED_FOR_FRAUD,
            "graveyard",
        ),
        (
            ApplicationStatusCodes.BANK_NAME_CORRECTED,
            ApplicationStatusCodes.APPLICATION_DENIED,
            "detour",
        ),
        (
            ApplicationStatusCodes.BANK_NAME_CORRECTED,
            ApplicationStatusCodes.NAME_VALIDATE_FAILED,
            "detour",
        ),
        (
            ApplicationStatusCodes.BANK_NAME_CORRECTED,
            ApplicationStatusCodes.CUSTOMER_ON_DELETION,
            "graveyard",
        ),
    ]
    for path in paths:
        is_exist = WorkflowStatusPath.objects.filter(
            status_previous=path[0], status_next=path[1], workflow=workflow
        ).exists()

        if is_exist:
            continue

        WorkflowStatusPath.objects.create(
            workflow=workflow,
            status_previous=path[0],
            status_next=path[1],
            type=path[2],
            is_active=True,
            customer_accessible=False,
            agent_accessible=True,
        )


class Migration(migrations.Migration):
    dependencies = []

    operations = [
        migrations.RunPython(run, migrations.RunPython.noop),
    ]
