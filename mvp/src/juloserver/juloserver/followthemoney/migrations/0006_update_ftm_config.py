# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import migrations
from juloserver.julo.constants import FeatureNameConst


def update_ftm_config(apps, _schema_editor):
    FeatureSetting = apps.get_model("julo", "FeatureSetting")
    featureSetting = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.FTM_CONFIGURATION
        ).first()

    if featureSetting:
        featureSetting.parameters = {"reassign_count":1}
        featureSetting.save()


class Migration(migrations.Migration):

    dependencies = [
        ('followthemoney', '0005_applicationlenderhistory'),
    ]

    operations = [
        migrations.RunPython(update_ftm_config, migrations.RunPython.noop)
    ]