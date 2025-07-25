# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2024-12-05 15:25
from __future__ import unicode_literals

from django.db import migrations
from django.contrib.auth.models import Group
from juloserver.portal.object.dashboard.constants import JuloUserRoles


def create_new_collection_roles(apps, schema_editor):
    split_bucket_roles = [
        JuloUserRoles.COLLECTION_TEAM_LEADER,
        JuloUserRoles.COLLECTION_AREA_COORDINATOR,
    ]
    for role in split_bucket_roles:
        Group.objects.get_or_create(name=role)


class Migration(migrations.Migration):

    dependencies = []

    operations = [
        migrations.RunPython(create_new_collection_roles, migrations.RunPython.noop),
    ]
