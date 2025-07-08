# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import migrations, models
from juloserver.julo.constants import FeatureNameConst


def auto_approval_global_setting(apps, _schema_editor):
    FeatureSetting = apps.get_model("julo", "FeatureSetting")
    current_setting = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.DEFAULT_LENDER_MATCHMAKING,
        category="followthemoney").update(
            parameters={"lender_name": "jtp"})

class Migration(migrations.Migration):

    dependencies = [
        ('followthemoney', '0043_enhancement_auto_approval'),
    ]

    operations = [
        migrations.RunPython(auto_approval_global_setting, migrations.RunPython.noop)
    ]