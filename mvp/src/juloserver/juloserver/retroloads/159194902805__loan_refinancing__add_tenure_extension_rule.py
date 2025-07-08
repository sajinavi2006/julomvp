# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import migrations
from juloserver.julo.constants import FeatureNameConst


from juloserver.julo.models import FeatureSetting



def add_tenure_extension_rule(apps, _schema_editor):
    
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
    ]

    operations = [
        migrations.RunPython(add_tenure_extension_rule, migrations.RunPython.noop)
    ]
