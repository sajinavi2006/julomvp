# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import migrations, models
from django.utils import timezone
from juloserver.julo.statuses import ApplicationStatusCodes
from juloserver.julo.constants import FeatureNameConst
from juloserver.julo.constants import ExperimentConst
import django.contrib.postgres.fields.jsonb

from juloserver.julo.models import WorkflowStatusPath


from juloserver.julo.models import Workflow


def add_new_status_path_for_icare(apps, _schema_editor):
    """
    Add status path (0->148) (148->177) (177->180)
    """
    
    workflow = Workflow.objects.filter(name="PartnerWorkflow").first()
    if workflow:
        
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
    ]

    operations = [
        migrations.RunPython(add_new_status_path_for_icare, migrations.RunPython.noop)
    ]
