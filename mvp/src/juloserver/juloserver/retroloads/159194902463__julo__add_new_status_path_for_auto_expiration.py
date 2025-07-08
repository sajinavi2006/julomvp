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


def add_new_status_path_for_auto_expiration(apps, schema_editor):
    
    cashloan_workflow = Workflow.objects.filter(name="CashLoanWorkflow").first()
    if cashloan_workflow:
        
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
    ]

    operations = [
        migrations.RunPython(add_new_status_path_for_auto_expiration, migrations.RunPython.noop)
    ]
