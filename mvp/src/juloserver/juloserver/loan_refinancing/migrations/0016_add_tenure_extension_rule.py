# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import migrations
from juloserver.julo.constants import FeatureNameConst


def add_tenure_extension_rule(apps, _schema_editor):
    FeatureSetting = apps.get_model("julo", "FeatureSetting")
    featuresetting = FeatureSetting.objects.get(
        is_active=True,
        feature_name=FeatureNameConst.COVID_REFINANCING,
        category="loan_refinancing",
    )

    featuresetting.parameters = {
        'email_expire_in_days': 10,
        'tenure_extension_rule': {'MTL_3': 2, 'MTL_4': 2, 'MTL_5': 3, 'MTL_6': 3}
    }
    featuresetting.save()


class Migration(migrations.Migration):

    dependencies = [
        ('loan_refinancing', '0015_remove_period_and_add_loan_duration'),
    ]

    operations = [
        migrations.RunPython(add_tenure_extension_rule, migrations.RunPython.noop)
    ]
