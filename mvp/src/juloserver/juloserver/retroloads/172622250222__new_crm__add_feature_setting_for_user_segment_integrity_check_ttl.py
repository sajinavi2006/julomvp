# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2024-09-13 10:15
from __future__ import unicode_literals

from django.db import migrations


from juloserver.julo.constants import FeatureNameConst
from juloserver.julo.models import FeatureSetting


def execute(apps, schema_editor):

    is_exist = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.USER_SEGMENT_CHUNK_INTEGRITY_CHECK_TTL,
    ).exists()
    if not is_exist:
        FeatureSetting.objects.create(
            feature_name=FeatureNameConst.USER_SEGMENT_CHUNK_INTEGRITY_CHECK_TTL,
            category='streamlined_communication',
            description='For chunking the user segment csv file on uploading',
            is_active=True,
            parameters={"TTL": 1800},
        )


class Migration(migrations.Migration):

    dependencies = []

    operations = [migrations.RunPython(execute, migrations.RunPython.noop)]
