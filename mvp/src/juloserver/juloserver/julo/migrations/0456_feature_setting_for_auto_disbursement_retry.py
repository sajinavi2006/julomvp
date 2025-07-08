# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import migrations
from juloserver.julo.constants import FeatureNameConst


def add_disbursement_auto_retry_feature_settings(apps, schema_editor):
    FeatureSetting = apps.get_model("julo", "FeatureSetting")
    FeatureSetting.objects.get_or_create(is_active=True,
        feature_name=FeatureNameConst.DISBURSEMENT_AUTO_RETRY,
        category="disbursement",
        parameters= {"max_retries": 3, "waiting_hours": 3},
        description="Disbursement auto retry setting, you can set max_retry and waiting_hour")


class Migration(migrations.Migration):

    dependencies = [
        ('julo', '0455_load_new_path_for_auto_disbursement'),
    ]

    operations = [
        migrations.RunPython(add_disbursement_auto_retry_feature_settings,
            migrations.RunPython.noop)
    ]
