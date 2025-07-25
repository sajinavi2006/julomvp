# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2017-03-15 06:33
from __future__ import unicode_literals

import logging

from django.db import connection
from django.db import migrations


logger = logging.getLogger(__name__)


def remove_duplicate_application_history(apps, schema_editor):
    """
    This migration procedure was missed when adding
    0031_update_application_status migration script and is now run as part of
    migrating to new process flow
    """

    ApplicationHistory = apps.get_model("julo", "ApplicationHistory")

    old_status_code = 150
    new_status_code = 141

    application_history_list = ApplicationHistory.objects.filter(
        status_old=old_status_code)
    for application_history in application_history_list:

        logger.info({
            'application_history': application_history,
            'application': application_history.application,
            'status_old': application_history.status_old
        })
        cursor = connection.cursor()
        cursor.execute(
            'UPDATE application_history SET status_old = %s WHERE application_history_id = %s; ',
            [new_status_code, application_history.id]
        )

    application_history_list = ApplicationHistory.objects.filter(
        status_new=old_status_code)
    for application_history in application_history_list:
        logger.info({
            'application_history': application_history,
            'application': application_history.application,
            'status_new': application_history.status_new
        })
        cursor = connection.cursor()
        cursor.execute(
            'UPDATE application_history SET status_new = %s WHERE application_history_id = %s; ',
            [new_status_code, application_history.id]
        )


class Migration(migrations.Migration):

    dependencies = [
        ('julo', '0034_image_resubmit'),
    ]

    operations = [
        migrations.RunPython(
            remove_duplicate_application_history
        ),
    ]
