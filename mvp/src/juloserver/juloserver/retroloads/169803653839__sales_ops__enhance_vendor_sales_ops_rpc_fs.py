# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2023-10-23 04:48
from __future__ import unicode_literals

from django.db import migrations

from juloserver.julo.models import FeatureSetting
from juloserver.sales_ops.constants import VendorRPCConst


def update_sales_ops_vendor_rpc_fs(app, schema_editor):
    fs = FeatureSetting.objects.get_or_none(feature_name=VendorRPCConst.FS_NAME)
    if not fs:
        return

    parameters = {
        "csv_headers": [
            "account_id",
            "vendor_id",
            "user_extension",
            "completed_date",
            "is_rpc",
        ],
        "date_fields": [
            "completed_date",
        ],
        "digit_fields": [
            "account_id",
            "vendor_id",
        ],
        "boolean_fields": [
            "is_rpc",
        ],
        "datetime_format": "%d/%m/%Y %H:%M:%S",
    }
    fs.update_safely(parameters=parameters)


class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.RunPython(update_sales_ops_vendor_rpc_fs, migrations.RunPython.noop)
    ]
