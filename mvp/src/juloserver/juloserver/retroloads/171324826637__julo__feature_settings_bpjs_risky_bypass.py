# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import migrations
from juloserver.julo.constants import FeatureNameConst
from juloserver.julo.models import FeatureSetting


def create_feature_settings_bpjs_risky_bypass(apps, _schema_editor):
    parameters = {
        "application_id": [0, 1, 2, 3, 4, 5, 6, 7, 8, 9],
    }
    FeatureSetting.objects.create(
        feature_name=FeatureNameConst.BPJS_RISKY_BYPASS,
        parameters=parameters,
        is_active=True,
        category='bpjs',
        description="Feature Setting to turn on/off BPJS Risky Bypass"
    )


class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.RunPython(create_feature_settings_bpjs_risky_bypass, migrations.RunPython.noop)
    ]
