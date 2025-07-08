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


def add_new_status_path_for_bypass_dv(apps, schema_editor):
    
    workflow = Workflow.objects.filter(name="PartnerWorkflow").first()
    if workflow:
        
        previous_statuses = 172
        WorkflowStatusPath.objects.get_or_create(
            status_previous=previous_statuses,
            status_next=150,
            type="happy",
            workflow= workflow
        )

class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.RunPython(add_new_status_path_for_bypass_dv, migrations.RunPython.noop)
    ]
