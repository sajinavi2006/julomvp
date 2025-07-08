# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import migrations, models
from django.utils import timezone
from ..statuses import ApplicationStatusCodes
from ..constants import FeatureNameConst
from ..constants import ExperimentConst
import django.contrib.postgres.fields.jsonb

def add_new_status_path_for_bypass_dv(apps, schema_editor):
    Workflow = apps.get_model("julo", "Workflow")
    workflows = Workflow.objects.filter(name__in=("CashLoanWorkflow", "LegacyWorkflow"))
    if workflows:
        for workflow in workflows:
            WorkflowStatusPath = apps.get_model("julo", "WorkflowStatusPath")
            previous_statuses = 120
            WorkflowStatusPath.objects.get_or_create(
                status_previous=previous_statuses,
                status_next=124,
                type="happy",
                workflow= workflow
            )

class Migration(migrations.Migration):

    dependencies = [
        ('julo', '0334_predictivemissedcall'),
    ]

    operations = [
        migrations.RunPython(add_new_status_path_for_bypass_dv, migrations.RunPython.noop)
    ]
