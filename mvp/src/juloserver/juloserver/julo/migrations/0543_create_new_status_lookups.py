# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import migrations

from ..statuses import ApplicationStatusCodes
from ..statuses import StatusManager


def create_new_status_lookups(apps, schema_editor):

    new_statuses = [
        ApplicationStatusCodes.BULK_DISBURSAL_ONGOING,
    ]

    StatusLookup = apps.get_model("julo", "StatusLookup")
    for new_status in new_statuses:
        status = StatusManager.get_or_none(new_status)
        StatusLookup.objects.create(
            status_code=status.code, status=status.desc
        )


class Migration(migrations.Migration):

    dependencies = [
        ('julo', '0542_new_status_path_bulk_disbursement'),
    ]

    operations = [
        migrations.RunPython(create_new_status_lookups)
    ]
