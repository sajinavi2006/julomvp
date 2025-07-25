# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2024-09-02 07:19
from __future__ import unicode_literals

from django.db import migrations
from juloserver.julo.constants import FeatureNameConst
from juloserver.julo.models import FeatureSetting


def execute(apps, schema_editor):

    setting = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.IDFY_VIDEO_CALL_HOURS
    ).last()
    if setting:
        new_parameters = setting.parameters
        new_parameters.update({'scheduler_messages': []})
        setting.update_safely(parameters=new_parameters)


class Migration(migrations.Migration):

    dependencies = []

    operations = [migrations.RunPython(execute, migrations.RunPython.noop)]
