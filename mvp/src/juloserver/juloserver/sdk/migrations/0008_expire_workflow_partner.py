# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import migrations, models
from django.utils import timezone
import django.contrib.postgres.fields.jsonb

def add_new_status_path_for_partner(apps, _schema_editor):
    """
    Add status path (148->135) reject application
    """
    Workflow = apps.get_model("julo", "Workflow")
    workflow = Workflow.objects.filter(name="PartnerWorkflow").first()
    if workflow:
        WorkflowStatusPath = apps.get_model("julo", "WorkflowStatusPath")
        DATA = [{"status_previous": 141, "status_next": 143},{"status_previous": 160, "status_next": 171}]
        for path in DATA:
            WorkflowStatusPath.objects.get_or_create(
                status_previous=path['status_previous'],
                status_next=path['status_next'],
                type="graveyard",
                workflow=workflow
            )

class Migration(migrations.Migration):

    dependencies = [
        ('sdk', '0007_load_pede_sphp'),
    ]

    operations = [
        migrations.RunPython(add_new_status_path_for_partner, migrations.RunPython.noop)
    ]
