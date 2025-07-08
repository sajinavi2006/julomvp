# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import migrations
from juloserver.julo.constants import FeatureNameConst


from juloserver.julo.models import FeatureSetting



def delay_c_scoring_feature_setting(apps, _schema_editor):
    
    FeatureSetting.objects.get_or_create(
        is_active=False,
        feature_name=FeatureNameConst.DELAY_C_SCORING,
        category="credit_score",
        parameters={'hours': '08:00', 'exact_time': False},
        description="Delay scoring and notifications for C credit score"
    )


class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.RunPython(delay_c_scoring_feature_setting, migrations.RunPython.noop)
    ]
