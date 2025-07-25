# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2024-07-03 05:22
from __future__ import unicode_literals

from django.db import migrations


def update_julo_core_expiry_marks(apps, schema_editor):
    from juloserver.julo.models import FeatureSetting
    from juloserver.julo.constants import FeatureNameConst

    feature = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.JULO_CORE_EXPIRY_MARKS
    ).last()
    parameters = feature.parameters

    if "x106_to_reapply" not in parameters:
        parameters["x106_to_reapply"] = 90

    if "x136_to_reapply" not in parameters:
        parameters["x136_to_reapply"] = 90

    feature.parameters = parameters
    feature.save()


class Migration(migrations.Migration):

    dependencies = []

    operations = [migrations.RunPython(update_julo_core_expiry_marks, migrations.RunPython.noop)]
