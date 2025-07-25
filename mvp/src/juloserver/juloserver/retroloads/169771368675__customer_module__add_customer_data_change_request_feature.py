# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2023-10-19 11:08
from __future__ import unicode_literals

from django.db import migrations

from juloserver.julo.constants import FeatureNameConst
from juloserver.julo.models import FeatureSetting


def add_customer_data_change_request_feature(*args):
    FeatureSetting.objects.get_or_create(
        feature_name=FeatureNameConst.CUSTOMER_DATA_CHANGE_REQUEST,
        defaults={
            "is_active": False,
            "category": "customer_module",
            "description": "The setting related to \"Ubah Data Pribadi\" CX-580",
            "parameters": {}
        }
    )


class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.RunPython(add_customer_data_change_request_feature, migrations.RunPython.noop)
    ]
