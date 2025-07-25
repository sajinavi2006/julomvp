# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2019-02-26 08:38
from __future__ import unicode_literals
from django.db import migrations
from juloserver.julo.management.commands import load_workflow, update_status_lookups, load_status_change_reasons


def create_new_status_digisign_failed(apps, schema_editor):
    opts = {'workflow_name': ('cash_loan',)}
    load_workflow.Command().handle(**opts)
    update_status_lookups.Command().handle()
    load_status_change_reasons.Command().handle()


class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.RunPython(create_new_status_digisign_failed)
    ]
