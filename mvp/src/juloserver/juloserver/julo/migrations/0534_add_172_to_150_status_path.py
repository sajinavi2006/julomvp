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
    workflow = Workflow.objects.filter(name="PartnerWorkflow").first()
    if workflow:
        WorkflowStatusPath = apps.get_model("julo", "WorkflowStatusPath")
        previous_statuses = 172
        WorkflowStatusPath.objects.get_or_create(
            status_previous=previous_statuses,
            status_next=150,
            type="happy",
            workflow= workflow
        )

class Migration(migrations.Migration):

    dependencies = [
        ('julo', '0533_pn_experiment_v2'),
    ]

    operations = [
        migrations.RunPython(add_new_status_path_for_bypass_dv, migrations.RunPython.noop)
    ]
