# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2022-01-14 02:00
from __future__ import unicode_literals

from django.db import migrations

from juloserver.application_flow.models import ApplicationTag, ApplicationPathTagStatus


def retro_new_application_tag_phase2(apps, schema_editor):
    application_tag_data = [
        ['is_dv', 4, 'sonic pass'],
    ]
    for application_tag in application_tag_data:
        ApplicationPathTagStatus.objects.create(
            application_tag=application_tag[0],
            status=application_tag[1],
            definition=application_tag[2])


class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.RunPython(retro_new_application_tag_phase2, migrations.RunPython.noop),
    ]

