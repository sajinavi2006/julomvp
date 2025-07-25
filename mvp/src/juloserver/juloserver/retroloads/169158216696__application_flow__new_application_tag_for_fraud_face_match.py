# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2023-08-09 11:56
from __future__ import unicode_literals

from django.db import migrations

from juloserver.application_flow.models import ApplicationTag

from juloserver.application_flow.models import ApplicationPathTagStatus


def retro_new_application_tag(apps, schema_editor):
    tag_data = [
        'is_fraud_face_match',
    ]
    for tag in tag_data:
        ApplicationTag.objects.create(application_tag=tag)

    application_tag_data = [
        ['is_fraud_face_match', -1, 'fail'],
        ['is_fraud_face_match', 1, 'success'],
        ['is_fraud_face_match', 0, 'not running'],
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
        migrations.RunPython(retro_new_application_tag, migrations.RunPython.noop),
    ]
