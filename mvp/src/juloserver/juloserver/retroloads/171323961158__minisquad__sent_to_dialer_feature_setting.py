# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2024-04-16 03:53
from __future__ import unicode_literals

from django.db import migrations

from juloserver.julo.models import FeatureSetting
from juloserver.minisquad.constants import FeatureNameConst


def add_feature_setting_sent_to_dialer_retroload(apps, schema_editor):
    parameters = {
        'start_date': '2024-04-02',  # start this issue raise by date team
        'end_date': '2024-04-30',  # this feature release
    }
    FeatureSetting.objects.create(
        feature_name=FeatureNameConst.SENT_TO_DIALER_RETROLOAD,
        is_active=True,
        description='config start and end date',
        category='dialer',
        parameters=parameters,
    )


class Migration(migrations.Migration):

    dependencies = []

    operations = [
        migrations.RunPython(
            add_feature_setting_sent_to_dialer_retroload, migrations.RunPython.noop
        )
    ]
