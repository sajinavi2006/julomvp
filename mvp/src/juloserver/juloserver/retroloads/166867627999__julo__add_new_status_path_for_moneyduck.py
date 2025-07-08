# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import migrations

from juloserver.julo.models import WorkflowStatusPath

from juloserver.julo.models import Workflow
from juloserver.julo.constants import WorkflowConst


def add_new_status_path_for_moneyduck(apps, _schema_editor):
    """
    Add status path (100->135) reject application
    """

    workflow = Workflow.objects.filter(name=WorkflowConst.JULO_ONE).last()
    if workflow:
        WorkflowStatusPath.objects.get_or_create(
            status_previous=100,
            status_next=135,
            type="graveyard",
            workflow=workflow
        )


class Migration(migrations.Migration):
    dependencies = [
    ]

    operations = [
        migrations.RunPython(add_new_status_path_for_moneyduck, migrations.RunPython.noop)
    ]
