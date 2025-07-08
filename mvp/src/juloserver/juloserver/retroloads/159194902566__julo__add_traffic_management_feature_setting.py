# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import migrations
from juloserver.julo.constants import FeatureNameConst


from juloserver.julo.models import FeatureSetting



def traffic_management_feature_setting(apps, _schema_editor):
    
    FeatureSetting.objects.get_or_create(
        is_active=True,
        feature_name=FeatureNameConst.DISBURSEMENT_TRAFFIC_MANAGE,
        category="traffic_managerment",
        parameters={'bca':{'bca':100, 'new_xfers':0}, 'xfers':{'xfers':100, 'new_xfers':0}},
        description="Config disbursement traffic"
    )


class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.RunPython(traffic_management_feature_setting, migrations.RunPython.noop)
    ]
