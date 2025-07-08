# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import migrations
from juloserver.julo.constants import FeatureNameConst


from juloserver.julo.models import FeatureSetting



def update_ftm_config(apps, _schema_editor):
    
    featureSetting = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.FTM_CONFIGURATION
        ).first()

    if featureSetting:
        featureSetting.parameters = {"reassign_count":1}
        featureSetting.save()


class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.RunPython(update_ftm_config, migrations.RunPython.noop)
    ]