# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import migrations, models
from juloserver.julo.constants import FeatureNameConst


from juloserver.julo.models import FeatureSetting



def auto_approval_global_setting(apps, _schema_editor):
    
    current_setting = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.DEFAULT_LENDER_MATCHMAKING,
        category="followthemoney").update(
            parameters={"lender_name": "jtp"})

class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.RunPython(auto_approval_global_setting, migrations.RunPython.noop)
    ]