# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import migrations
from juloserver.julo.constants import FeatureNameConst


from juloserver.julo.models import FeatureSetting



def ftm_config_feature_setting(apps, _schema_editor):
    
    FeatureSetting.objects.get_or_create(is_active=True,
        feature_name=FeatureNameConst.FTM_CONFIGURATION,
        category="followthemoney",
        parameters= {},
        description="FTM Configuration, so lender need to process 1 by 1 and by a confirm button")


class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.RunPython(ftm_config_feature_setting, migrations.RunPython.noop)
    ]