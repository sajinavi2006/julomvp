# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import migrations
from juloserver.julo.constants import FeatureNameConst


def delay_c_scoring_feature_setting(apps, _schema_editor):
    featuresetting = apps.get_model("julo", "FeatureSetting")
    featuresetting.objects.get_or_create(
        is_active=False,
        feature_name=FeatureNameConst.DELAY_C_SCORING,
        category="credit_score",
        parameters={'hours': '08:00', 'exact_time': False},
        description="Delay scoring and notifications for C credit score"
    )


class Migration(migrations.Migration):

    dependencies = [
        ('julo', '0661_add_column_spoke_with_to_centerix'),
    ]

    operations = [
        migrations.RunPython(delay_c_scoring_feature_setting, migrations.RunPython.noop)
    ]
