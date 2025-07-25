# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2023-10-09 09:56
from __future__ import unicode_literals

from django.db import migrations
from juloserver.julo.models import FeatureSetting
from juloserver.promo.constants import FeatureNameConst


def add_new_fs_for_whitelist_promo_code_list(apps, schema_editor):
    FeatureSetting.objects.create(
        feature_name=FeatureNameConst.PROMO_CODE_WHITELIST_CUST,
        is_active=True,
        category='promo',
        parameters={'customer_ids': []}
    )


class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.RunPython(add_new_fs_for_whitelist_promo_code_list, migrations.RunPython.noop)
    ]
