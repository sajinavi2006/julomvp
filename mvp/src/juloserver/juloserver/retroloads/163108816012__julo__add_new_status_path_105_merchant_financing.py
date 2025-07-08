# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import migrations

from juloserver.julo.models import WorkflowStatusPath, Workflow
from juloserver.julo.constants import WorkflowConst


def add_new_status_path_100_to_105_for_merchant_financing(apps, _schema_editor):

    workflow = Workflow.objects.filter(name=WorkflowConst.MERCHANT_FINANCING_WORKFLOW).first()
    if workflow:
        WorkflowStatusPath.objects.get_or_create(
            status_previous=100,
            status_next=105,
            type="happy",
            workflow=workflow
        )


class Migration(migrations.Migration):
    dependencies = [
    ]

    operations = [
        migrations.RunPython(add_new_status_path_100_to_105_for_merchant_financing,
                             migrations.RunPython.noop)
    ]
