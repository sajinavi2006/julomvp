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


def reactivate_122_to_130_for_pva_bypass(apps, schema_editor):
    
    workflow = Workflow.objects.filter(name="CashLoanWorkflow")
    if workflow:
        
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
    ]

    operations = [
        migrations.RunPython(reactivate_122_to_130_for_pva_bypass, migrations.RunPython.noop)
    ]
