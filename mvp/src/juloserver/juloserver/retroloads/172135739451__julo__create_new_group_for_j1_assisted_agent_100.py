# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2024-07-19 02:49
from __future__ import unicode_literals

from django.db import migrations
from django.contrib.auth.models import Group
from juloserver.portal.object.dashboard.constants import JuloUserRoles


def execute_retroload(apps, schema_editor):
    if not Group.objects.filter(name=JuloUserRoles.J1_AGENT_ASSISTED_100).exists():
        Group.objects.create(name=JuloUserRoles.J1_AGENT_ASSISTED_100)


class Migration(migrations.Migration):

    dependencies = []

    operations = [migrations.RunPython(execute_retroload, migrations.RunPython.noop)]
