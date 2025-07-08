# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import migrations, models
from django.utils import timezone
from ..statuses import ApplicationStatusCodes
from ..constants import FeatureNameConst
from ..constants import ExperimentConst
import django.contrib.postgres.fields.jsonb

def add_new_status_path_for_auto_expiration(apps, schema_editor):
    Workflow = apps.get_model("julo", "Workflow")
    cashloan_workflow = Workflow.objects.filter(name="CashLoanWorkflow").first()
    if cashloan_workflow:
        WorkflowStatusPath = apps.get_model("julo", "WorkflowStatusPath")
        previous_statuses = [162,175]
        for status_previous in previous_statuses:
            WorkflowStatusPath.objects.get_or_create(
                status_previous=status_previous,
                status_next=143,
                type="detour",
                workflow= cashloan_workflow
            )

class Migration(migrations.Migration):

    dependencies = [
        ('julo', '0329_auto_20190110_1557'),
    ]

    operations = [
        migrations.RunPython(add_new_status_path_for_auto_expiration, migrations.RunPython.noop)
    ]
