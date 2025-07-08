# -*- coding: utf-8 -*-
from __future__ import unicode_literals
from django.db import migrations, models
from juloserver.julo.statuses import ApplicationStatusCodes
from ..management.commands import update_status_lookups


def create_new_handler_for_174(apps, schema_editor):
    update_status_lookups.Command().handle()

class Migration(migrations.Migration):

    dependencies = [
        ('julo', '0568_change_lender_lender_table'),
    ]

    operations = [
        migrations.RunPython(create_new_handler_for_174),
    ]
