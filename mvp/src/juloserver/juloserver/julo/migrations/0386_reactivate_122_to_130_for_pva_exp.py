# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import migrations, models
from django.utils import timezone
from ..statuses import ApplicationStatusCodes
from ..constants import FeatureNameConst
from ..constants import ExperimentConst
import django.contrib.postgres.fields.jsonb

def reactivate_122_to_130_for_pva_bypass(apps, schema_editor):
    Workflow = apps.get_model("julo", "Workflow")
    workflow = Workflow.objects.filter(name="CashLoanWorkflow")
    if workflow:
        WorkflowStatusPath = apps.get_model("julo", "WorkflowStatusPath")
        status_path = WorkflowStatusPath.objects.filter(
            status_previous=122,
            status_next=130,
            workflow= workflow
        ).last()
        if status_path:
            status_path.is_active=True
            status_path.agent_accessible = False
            status_path.save()

class Migration(migrations.Migration):

    dependencies = [
        ('julo', '0385_load_bypass_pva_experiment'),
    ]

    operations = [
        migrations.RunPython(reactivate_122_to_130_for_pva_bypass, migrations.RunPython.noop)
    ]
