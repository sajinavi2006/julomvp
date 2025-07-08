# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import migrations
from juloserver.julo.constants import FeatureNameConst


from juloserver.julo.models import FeatureSetting



def create_feature_settings_fdc_inquiry_check(apps, _schema_editor):
    
    parameters = {
        "min_threshold": 0.65,
        "max_threshold": 0.90
    }
    FeatureSetting.objects.create(
        feature_name=FeatureNameConst.FDC_INQUIRY_CHECK,
        parameters=parameters,
        is_active=True,
        category='fdc',
        description="Feature Setting to turn on/off fdc inquiry check"
    )


class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.RunPython(create_feature_settings_fdc_inquiry_check, migrations.RunPython.noop)
    ]
