# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import migrations
from juloserver.julo.constants import FeatureNameConst


from juloserver.julo.models import FeatureSetting



def mintos_interest_rate_feature_setting(apps, _schema_editor):
    
    FeatureSetting.objects.get_or_create(
        is_active=True,
        feature_name=FeatureNameConst.MINTOS_INTEREST_RATE,
        category="mintos_interest_rate",
        parameters={'interest_rate_percent': 15},
        description="Config mintos interest rate percent"
    )


class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.RunPython(mintos_interest_rate_feature_setting, migrations.RunPython.noop)
    ]
