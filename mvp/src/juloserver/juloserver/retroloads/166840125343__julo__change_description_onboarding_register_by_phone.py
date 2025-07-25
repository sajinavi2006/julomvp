# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2022-11-14 04:47
from __future__ import unicode_literals

from django.db import migrations
from juloserver.julo.models import Onboarding


def change_description_onboarding(apps, schema_editor):
    """
    For change description onboarding_id 4 & 5

    Refer to the ticket:
    https://juloprojects.atlassian.net/browse/RUS1-1317
    """

    update_rows = [
        {
            'id': 4,
            'description': 'Register with Phone Number, Email and NIK AND Long Form'
        },
        {
            'id': 5,
            'description': 'Register with Phone Number, Email and NIK AND Long Form Shortened'
        }
    ]

    for data in update_rows:
        Onboarding.objects.filter(id=data['id']).update(description=data['description'])


class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.RunPython(change_description_onboarding, migrations.RunPython.noop)
    ]
