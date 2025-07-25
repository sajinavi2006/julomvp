# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2017-10-31 04:04
from __future__ import unicode_literals

from django.db import migrations


from juloserver.julo.models import StatusLookup



def db_insert_form_partial_statuses(apps, schema_editor):
    
    StatusLookup.objects.get_or_create(status_code=105,
                                       status='Form partial')
    StatusLookup.objects.get_or_create(status_code=106,
                                       status='Form partial expired')


class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.RunPython(db_insert_form_partial_statuses, migrations.RunPython.noop)
    ]
