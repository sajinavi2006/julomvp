# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2022-06-06 09:52
from __future__ import unicode_literals
from django.db import migrations
from django.contrib.auth.models import Group

from juloserver.portal.object.dashboard.constants import JuloUserRoles


def create_ops_repayment_group(apps, schema_editor):
    new_group, _ = Group.objects.get_or_create(name=JuloUserRoles.OPS_REPAYMENT)


class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.RunPython(create_ops_repayment_group, migrations.RunPython.noop),
    ]
