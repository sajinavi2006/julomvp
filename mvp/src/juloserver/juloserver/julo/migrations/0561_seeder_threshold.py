# -*- coding: utf-8 -*-
from __future__ import unicode_literals
from django.db import migrations
from juloserver.julo.management.commands import retroload_credit_matrix


def new_partner_178_handler(apps, schema_editor):
    retroload_credit_matrix.Command().handle()


class Migration(migrations.Migration):

    dependencies = [
        ('julo', '0560_job_type_seeder'),
    ]

    operations = [
        migrations.RunPython(new_partner_178_handler)
    ]
