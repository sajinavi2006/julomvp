# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2025-03-12 04:27
from __future__ import unicode_literals

from django.db import migrations

from juloserver.grab.constants import GrabFeatureNameConst
from juloserver.grab.models import GrabFeatureSetting


def add_feature_setting_for_grab_halt_resume(app, _schema_editor):
    GrabFeatureSetting.objects.get_or_create(
        is_active=False,
        category="grab collection",
        description='grab halt resume Feature setting',
        feature_name=GrabFeatureNameConst.GRAB_HALT_RESUME_DISBURSAL_PERIOD,
        parameters={
            "loan_halt_date": "2025-03-28",
            "loan_resume_date": "2025-04-06",
        },
    )


class Migration(migrations.Migration):

    dependencies = []

    operations = [
        migrations.RunPython(add_feature_setting_for_grab_halt_resume, migrations.RunPython.noop),
    ]
