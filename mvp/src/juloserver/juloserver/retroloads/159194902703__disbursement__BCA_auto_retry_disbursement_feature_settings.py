# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import migrations
from juloserver.julo.constants import FeatureNameConst
from juloserver.julo.models import FeatureSetting


def add_disbursement_auto_retry_bca_feature_settings(apps, schema_editor):
    FeatureSetting.objects.get_or_create(is_active=True,
        feature_name=FeatureNameConst.BCA_DISBURSEMENT_AUTO_RETRY,
        category="disbursement",
        parameters= {"max_retries": 3, "delay_in_hours": 4},
        description="Disbursement auto retry setting for BCA, you can set max_retry and delay_in_hours")


class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.RunPython(add_disbursement_auto_retry_bca_feature_settings,
            migrations.RunPython.noop)
    ]
