# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import migrations
from juloserver.julo.constants import FeatureNameConst


def create_feature_settings_fraud_model(apps, _schema_editor):
    featuresetting = apps.get_model("julo", "FeatureSetting")
    parameters = {
        "high_probability_fpd": 0.73,
        "low_probability_fpd": 0.73
    }
    featuresetting.objects.create(
        feature_name=FeatureNameConst.FRAUD_MODEL_EXPERIMENT,
        parameters=parameters,
        is_active=True,
        description="Making Fraud Model as part of binary check"
    )


class Migration(migrations.Migration):

    dependencies = [
        ('julo', '0604_create_experiment_fraud_model'),
    ]

    operations = [
        migrations.RunPython(create_feature_settings_fraud_model, migrations.RunPython.noop)
    ]
