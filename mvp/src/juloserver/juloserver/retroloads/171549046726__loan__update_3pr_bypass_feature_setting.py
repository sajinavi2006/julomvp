# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2024-05-12 05:07
from __future__ import unicode_literals

from django.db import migrations
from juloserver.julo.constants import FeatureNameConst
from juloserver.julo.models import FeatureSetting


def update_3pr_bypass_pgood_feature_setting(apps, schema_editor):
    fs = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.CHECK_OTHER_ACTIVE_PLATFORMS_USING_FDC,
        category="loan",
    ).first()
    if fs:
        c_score_bypass = fs.parameters.get('c_score_bypass')
        if c_score_bypass:
            c_score_bypass.update(pgood_gte=0.75)
            fs.parameters.update(c_score_bypass=c_score_bypass)
            fs.save()


class Migration(migrations.Migration):

    dependencies = []

    operations = [
        migrations.RunPython(update_3pr_bypass_pgood_feature_setting, migrations.RunPython.noop),
    ]
