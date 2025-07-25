# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2025-06-23 02:32
from __future__ import unicode_literals

from django.db import migrations
from juloserver.julo.models import FeatureSetting
from juloserver.julo.constants import FeatureNameConst


def run(apps, schema_editor):

    setting = FeatureSetting.objects.filter(feature_name=FeatureNameConst.REPOPULATE_ZIPCODE).last()
    if not setting:
        return

    new_parameters = setting.parameters
    new_parameters.update({'only_status_code': 190, 'is_active_specific_status': True})
    setting.update_safely(parameters=new_parameters)


class Migration(migrations.Migration):

    dependencies = []

    operations = [
        migrations.RunPython(
            run,
            migrations.RunPython.noop,
        ),
    ]
