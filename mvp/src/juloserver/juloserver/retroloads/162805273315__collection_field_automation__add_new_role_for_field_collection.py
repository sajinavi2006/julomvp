# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2021-08-04 04:52
from __future__ import unicode_literals

from django.db import migrations
from django.contrib.auth.models import Group
from juloserver.portal.object.dashboard.constants import JuloUserRoles


def add_collection_field_roles(apps, schema_editor):
    collection_field_roles = [
        JuloUserRoles.COLLECTION_FIELD_AGENT,
    ]
    for role in collection_field_roles:
        Group.objects.get_or_create(name=role)


class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.RunPython(add_collection_field_roles)
    ]
