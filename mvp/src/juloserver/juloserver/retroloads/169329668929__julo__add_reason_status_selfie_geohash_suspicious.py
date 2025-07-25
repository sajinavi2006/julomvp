# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2023-08-29 08:11
from __future__ import unicode_literals

from django.db import migrations

from juloserver.fraud_security.constants import FraudChangeReason
from juloserver.julo.models import ChangeReason
from juloserver.julo.statuses import ApplicationStatusCodes


def add_change_reason_id(_apps, _schema_editor):
    ChangeReason.objects.get_or_create(
        reason=FraudChangeReason.SELFIE_IN_GEOHASH_SUSPICIOUS,
        status_id=ApplicationStatusCodes.APPLICATION_FLAGGED_FOR_FRAUD_SUSPICIOUS
    )

    revert_statuses = [
        ApplicationStatusCodes.SCRAPED_DATA_VERIFIED,
        ApplicationStatusCodes.APPLICATION_RESUBMITTED,
    ]
    for revert_status in revert_statuses:
        ChangeReason.objects.get_or_create(
            reason="Pass Selfie Geohash",
            status_id=revert_status,
        )

class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.RunPython(add_change_reason_id, migrations.RunPython.noop)
    ]
