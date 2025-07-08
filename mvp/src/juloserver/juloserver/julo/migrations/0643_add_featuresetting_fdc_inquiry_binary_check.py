# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import migrations
from juloserver.julo.constants import FeatureNameConst


def create_feature_settings_fdc_inquiry_check(apps, _schema_editor):
    featuresetting = apps.get_model("julo", "FeatureSetting")
    parameters = {
        "min_threshold": 0.65,
        "max_threshold": 0.90
    }
    featuresetting.objects.create(
        feature_name=FeatureNameConst.FDC_INQUIRY_CHECK,
        parameters=parameters,
        is_active=True,
        category='fdc',
        description="Feature Setting to turn on/off fdc inquiry check"
    )


class Migration(migrations.Migration):

    dependencies = [
        ('julo', '0642_change_table_c_user_feedback_to_user_feedback'),
    ]

    operations = [
        migrations.RunPython(create_feature_settings_fdc_inquiry_check, migrations.RunPython.noop)
    ]
