# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2023-08-31 06:20
from __future__ import unicode_literals

from django.db import migrations

from juloserver.julo.models import FeatureSetting
from juloserver.promo.constants import FeatureNameConst


def create_feature_setting_promo_entry_page(app, schema_editor):
    FeatureSetting.objects.create(
        feature_name=FeatureNameConst.PROMO_ENTRY_PAGE,
        is_active=False
    )


class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.RunPython(create_feature_setting_promo_entry_page, migrations.RunPython.noop)
    ]
