# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import migrations
from juloserver.julo.constants import FeatureNameConst


def update_tenure_extension_rule(apps, _schema_editor):
    FeatureSetting = apps.get_model("julo", "FeatureSetting")
    featuresetting = FeatureSetting.objects.get(
        is_active=True,
        feature_name=FeatureNameConst.COVID_REFINANCING,
        category="loan_refinancing",
    )

    featuresetting.parameters.update({
        'tenure_extension_rule': {
            'MTL_2': 2,
            'MTL_3': 2,
            'MTL_4': 2,
            'MTL_5': 3,
            'MTL_6': 3,
            'MTL_7': 3,
            'MTL_8': 3,
            'MTL_9': 3}
    })
    
    featuresetting.save()


class Migration(migrations.Migration):

    dependencies = [
        ('loan_refinancing', '0016_add_tenure_extension_rule'),
    ]

    operations = [
        migrations.RunPython(update_tenure_extension_rule, migrations.RunPython.noop)
    ]
