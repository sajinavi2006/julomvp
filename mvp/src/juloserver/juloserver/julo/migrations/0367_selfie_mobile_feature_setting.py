# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import migrations


def create_form_selfie_mobile_setting(apps, schema_editor):
    MobileFeatureSetting = apps.get_model("julo", "MobileFeatureSetting")
    setting = MobileFeatureSetting(
        feature_name="form_selfie",
        parameters={},
    )
    setting.save()


class Migration(migrations.Migration):

    dependencies = [
        ('julo', '0366_disable_v20b_score_feature'),
    ]

    operations = [
        migrations.RunPython(create_form_selfie_mobile_setting),
    ]
