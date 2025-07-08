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


def add_new_status_path_for_revive_mtl(apps, schema_editor):
    
    workflow = Workflow.objects.filter(name="JuloOneWorkflow").last()
            
    WorkflowStatusPath.objects.get_or_create(
        status_previous=175,
        status_next=141,
        type="happy",
        workflow= workflow
    )

class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.RunPython(add_new_status_path_for_revive_mtl, migrations.RunPython.noop)
    ]
