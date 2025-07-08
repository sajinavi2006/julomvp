# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import migrations
from juloserver.promo.management.commands import update_customer_marked_risky


def update_customer_data_marked_risky(apps, schema_editor):
    update_customer_marked_risky.Command().handle()


class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.RunPython(update_customer_data_marked_risky,
            migrations.RunPython.noop)
    ]
