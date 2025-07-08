# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import migrations
from juloserver.julo.constants import FeatureNameConst


from juloserver.julo.models import FeatureSetting



def covid_refinancing_feature_setting(apps, _schema_editor):
    
    FeatureSetting.objects.get_or_create(
        is_active=True,
        feature_name=FeatureNameConst.COVID_REFINANCING,
        category="loan_refinancing",
        parameters={'email_expire_in_days': 10, 'covid_period_end_month': 7,  'covid_period_end_year': 2020},
        description="Config for loan refinancing special in covid period"
    )


class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.RunPython(covid_refinancing_feature_setting, migrations.RunPython.noop)
    ]
