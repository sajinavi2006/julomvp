# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import migrations, models
from juloserver.julo.constants import FeatureNameConst


def add_feature_setting_for_loan_refinancing(apps, _schema_editor):
    FeatureSetting = apps.get_model("julo", "FeatureSetting")

    FeatureSetting.objects.get_or_create(
        is_active=False,
        feature_name=FeatureNameConst.LOAN_REFINANCING,
        category="loan_refinancing",
        description="Setting to send loan refinancing email to eligible cuwtomers")


class Migration(migrations.Migration):

    dependencies = [
        ('julo', '0651_seed_customer_reliability_score_on_skiptrace_result_choice'),
    ]

    operations = [
        migrations.RunPython(add_feature_setting_for_loan_refinancing, migrations.RunPython.noop)
    ]
