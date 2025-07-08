# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import migrations


from juloserver.julo.models import WorkflowStatusPath



from juloserver.julo.models import Workflow



def add_new_status_path_for_followthemoney(apps, _schema_editor):
    """
    Add status path (165->135) reject application
    """
    
    workflow = Workflow.objects.filter(name="CashLoanWorkflow").first()
    if workflow:
        
        WorkflowStatusPath.objects.get_or_create(
            status_previous=165,
            status_next=135,
            type="detour",
            workflow=workflow
        )


class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.RunPython(add_new_status_path_for_followthemoney, migrations.RunPython.noop)
    ]
