# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import migrations
from juloserver.julo.constants import FeatureNameConst

from juloserver.julo.models import FeatureSetting


def add_web_model_fdc_retry_setting_feature(apps, schema_editor):
    FeatureSetting.objects.get_or_create(
        is_active=True,
        feature_name=FeatureNameConst.WEB_MODEL_FDC_RETRY_SETTING,
        category="Web Application",
        parameters={'threshold_in_hours': 3},
        description="Define the threshold limit (in hours) for FDC retry mechanism before call web model "
     )


class Migration(migrations.Migration):
    dependencies = [
    ]

    operations = [
        migrations.RunPython(add_web_model_fdc_retry_setting_feature, migrations.RunPython.noop)
    ]
