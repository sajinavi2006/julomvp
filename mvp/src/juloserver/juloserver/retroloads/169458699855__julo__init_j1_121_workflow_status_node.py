# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2023-09-13 06:36
from __future__ import unicode_literals

from django.db import migrations

from juloserver.julo.constants import WorkflowConst, ApplicationStatusCodes
from juloserver.julo.models import Workflow, WorkflowStatusNode


def run(apps, _schema_editor):
    workflow = Workflow.objects.filter(name=WorkflowConst.JULO_ONE).last()
    data = dict(
        status_node=ApplicationStatusCodes.SCRAPED_DATA_VERIFIED,
        handler='JuloOne121Handler',
        workflow=workflow
    )
    if WorkflowStatusNode.objects.filter(**data).exists():
        return

    WorkflowStatusNode.objects.create(**data)


class Migration(migrations.Migration):
    dependencies = [
    ]

    operations = [
        migrations.RunPython(
            run,
            migrations.RunPython.noop
        ),
    ]
