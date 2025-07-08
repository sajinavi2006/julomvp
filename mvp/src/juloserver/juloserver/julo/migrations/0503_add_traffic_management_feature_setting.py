# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import migrations
from juloserver.julo.constants import FeatureNameConst


def traffic_management_feature_setting(apps, _schema_editor):
    featuresetting = apps.get_model("julo", "FeatureSetting")
    featuresetting.objects.get_or_create(
        is_active=True,
        feature_name=FeatureNameConst.DISBURSEMENT_TRAFFIC_MANAGE,
        category="traffic_managerment",
        parameters={'bca':{'bca':100, 'new_xfers':0}, 'xfers':{'xfers':100, 'new_xfers':0}},
        description="Config disbursement traffic"
    )


class Migration(migrations.Migration):

    dependencies = [
        ('julo', '0502_cm_v25'),
    ]

    operations = [
        migrations.RunPython(traffic_management_feature_setting, migrations.RunPython.noop)
    ]
