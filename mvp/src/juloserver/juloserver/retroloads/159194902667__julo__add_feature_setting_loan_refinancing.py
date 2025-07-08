# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import migrations, models
from juloserver.julo.constants import FeatureNameConst


from juloserver.julo.models import FeatureSetting



def add_feature_setting_for_loan_refinancing(apps, _schema_editor):
    

    FeatureSetting.objects.get_or_create(
        is_active=False,
        feature_name=FeatureNameConst.LOAN_REFINANCING,
        category="loan_refinancing",
        description="Setting to send loan refinancing email to eligible cuwtomers")


class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.RunPython(add_feature_setting_for_loan_refinancing, migrations.RunPython.noop)
    ]
