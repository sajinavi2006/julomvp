# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import migrations
from juloserver.julo.constants import FeatureNameConst


from juloserver.julo.models import FeatureSetting



def suspend_account_feature_settings(apps, schema_editor):
    
    parameters = dict(suspend_delay=1)
    FeatureSetting.objects.get_or_create(is_active=False,
                                         feature_name=FeatureNameConst.SUSPEND_ACCOUNT_PAYLATER,
                                         parameters=parameters,
                                         category="paylater",
                                         description="Delay time before suspend account paylater"
                                         )


class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.RunPython(suspend_account_feature_settings,
                             migrations.RunPython.noop)
    ]
