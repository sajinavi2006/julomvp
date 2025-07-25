# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2025-05-14 13:43
from __future__ import unicode_literals

from django.db import migrations
from juloserver.julo.models import FeatureSetting
from juloserver.julo.constants import FeatureNameConst


def execute(apps, schema_editor):

    setting = FeatureSetting.objects.filter(feature_name=FeatureNameConst.REPOPULATE_ZIPCODE).last()

    if not setting:
        return

    new_parameters = setting.parameters
    new_parameters.update({'limit_exclude_apps': 10000})
    setting.update_safely(parameters=new_parameters)


class Migration(migrations.Migration):

    dependencies = []

    operations = [migrations.RunPython(execute, migrations.RunPython.noop)]
