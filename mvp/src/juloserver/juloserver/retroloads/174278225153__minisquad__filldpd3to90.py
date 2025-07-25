# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2025-03-24 02:10
from __future__ import unicode_literals

from django.db import migrations

from juloserver.julo.models import FeatureSetting
from juloserver.minisquad.constants import FeatureNameConst


def add_feature_setting_dialer_dpd3_to_90(app, _schema_editor):
    feature_setting, _ = FeatureSetting.objects.get_or_create(
        feature_name=FeatureNameConst.BUCKET_RECOVERY_DISTRIBUTION,
        is_active=True,
        description="bucket recovery distribution setting",
        category="dialer",
        parameters={},
    )

    parameters = feature_setting.parameters
    parameters["FCB1"] = {
        "is_running": True,
        "dc_vendor_setting": {"limit": 50000, "dpd_max": 90, "dpd_min": 3, "run_day": 13},
        "fc_vendor_setting": {
            "limit": 7,
            "dpd_max": 90,
            "dpd_min": 3,
            "run_day": 13,
            "zipcode_coverage": ["99322", "99323", "31458", "31459"],
        },
        "dc_inhouse_setting": {"limit": 0, "dpd_max": 90, "dpd_min": 3, "run_day": 0},
        "fc_inhouse_setting": {
            "dpd_max": 60,
            "dpd_min": 3,
            "run_day": 1,
        },
    }
    feature_setting.parameters = parameters
    feature_setting.save()


class Migration(migrations.Migration):

    dependencies = []

    operations = [
        migrations.RunPython(add_feature_setting_dialer_dpd3_to_90, migrations.RunPython.noop),
    ]
