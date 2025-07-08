# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import migrations, models
from django.utils import timezone
from ..statuses import ApplicationStatusCodes
from ..constants import FeatureNameConst
from ..constants import ExperimentConst
import django.contrib.postgres.fields.jsonb

def add_new_status_path_for_icare(apps, _schema_editor):
    """
    Add status path (0->148) (148->177) (177->180)
    """
    Workflow = apps.get_model("julo", "Workflow")
    workflow = Workflow.objects.filter(name="PartnerWorkflow").first()
    if workflow:
        WorkflowStatusPath = apps.get_model("julo", "WorkflowStatusPath")
        WorkflowStatusPath.objects.get_or_create(
            status_previous=0,
            status_next=148,
            type="happy",
            workflow=workflow
        )

        WorkflowStatusPath.objects.get_or_create(
            status_previous=148,
            status_next=177,
            type="happy",
            workflow=workflow
        )

        WorkflowStatusPath.objects.get_or_create(
            status_previous=177,
            status_next=180,
            type="happy",
            workflow=workflow
        )
class Migration(migrations.Migration):

    dependencies = [
        ('julo', '0411_auto_20190408_1750'),
    ]

    operations = [
        migrations.RunPython(add_new_status_path_for_icare, migrations.RunPython.noop)
    ]
