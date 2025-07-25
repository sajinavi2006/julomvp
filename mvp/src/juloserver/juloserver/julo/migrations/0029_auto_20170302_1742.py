# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2016-12-29 06:11
from __future__ import unicode_literals

import logging

from django.contrib.auth.models import Group
from django.contrib.auth.models import Permission
from django.core import exceptions
from django.db import migrations


logger = logging.getLogger(__name__)


def create_julo_partners_group(apps, schema_editor):

    new_group, _ = Group.objects.get_or_create(name='julo_partners')

    permission_codenames_to_be_added = [
        'add_partnerreferral',
        'add_partnertransaction',
        'add_partnertransactionitem'
    ]

    for codename in permission_codenames_to_be_added:
        try:
            permission = Permission.objects.get(codename=codename)
        except exceptions.ObjectDoesNotExist:
            # This condition needs to be caught for running unit tests
            logger.warn({
                'permission_codename': codename,
                'status': 'does_not_exist'
            })
            continue
        new_group.permissions.add(permission)


class Migration(migrations.Migration):

    dependencies = [
        ('julo', '0028_paymentevent'),
    ]

    operations = [
        migrations.RunPython(create_julo_partners_group),
    ]
