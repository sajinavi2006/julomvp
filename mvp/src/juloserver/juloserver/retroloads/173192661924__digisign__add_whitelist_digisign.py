# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2024-11-18 10:43
from __future__ import unicode_literals

from django.db import migrations
from juloserver.julo.constants import FeatureNameConst
from juloserver.julo.models import FeatureSetting


def add_whitelist_digisign_feature_setting(apps, schema_editor):
    FeatureSetting.objects.create(
        feature_name=FeatureNameConst.WHITELIST_DIGISIGN,
        is_active=True,
        parameters={
            "customer_ids": []
        },
        description='whitelist digisign'
    )


class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.RunPython(
            add_whitelist_digisign_feature_setting, migrations.RunPython.noop
        )
    ]
