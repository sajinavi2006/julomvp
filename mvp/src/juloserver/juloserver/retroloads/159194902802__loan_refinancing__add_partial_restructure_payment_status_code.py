# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import migrations
from juloserver.julo.management.commands import update_status_lookups


def create_new_payment_status(apps, schema_editor):
    update_status_lookups.Command().handle()


class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.RunPython(create_new_payment_status,
            migrations.RunPython.noop)
    ]
