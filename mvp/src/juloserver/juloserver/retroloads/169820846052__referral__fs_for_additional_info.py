# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2023-10-25 04:34
from __future__ import unicode_literals

from django.db import migrations
from juloserver.julo.models import FeatureSetting
from juloserver.referral.constants import FeatureNameConst


def add_new_referral_fs_for_additional_info(apps, schema_editor):
    FeatureSetting.objects.create(
        feature_name=FeatureNameConst.ADDITIONAL_INFO,
        is_active=False,
        category='referral',
        parameters={
            'info_content': (
                '*Cashback referral bisa digunakan mulai tanggal 1 '
                'Januari 2024 atau 45 hari setelah cashback diterima'
            )
        }
    )



class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.RunPython(add_new_referral_fs_for_additional_info, migrations.RunPython.noop)
    ]
