# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2023-12-12 01:53
from __future__ import unicode_literals

from django.db import migrations

from juloserver.payback.models import DanaBillerStatus
from juloserver.payback.constants import DanaBillerStatusCodeConst


statuses = [
    DanaBillerStatus(
        code=DanaBillerStatusCodeConst.SUCCESS,
        is_success=True,
        message="Success",
    ),
    DanaBillerStatus(
        code=DanaBillerStatusCodeConst.INVALID_DESTINATION,
        is_success=False,
        message="Invalid Destination",
    ),
    DanaBillerStatus(
        code=DanaBillerStatusCodeConst.BILL_NOT_AVAILABLE,
        is_success=False,
        message="Bill is not available",
    ),
    DanaBillerStatus(
        code=DanaBillerStatusCodeConst.TRANSACTION_FAILED,
        is_success=False,
        message="Transaction failed",
    ),
    DanaBillerStatus(
        code=DanaBillerStatusCodeConst.GENERAL_ERROR,
        is_success=False,
        message="General Error",
    ),
    DanaBillerStatus(
        code=DanaBillerStatusCodeConst.DATA_NOT_FOUND,
        is_success=False,
        message="Data not found",
    ),
]

def add_dana_biller_status(apps, _schema_editor):
    DanaBillerStatus.objects.bulk_create(statuses)


class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.RunPython(add_dana_biller_status, migrations.RunPython.noop),
    ]
