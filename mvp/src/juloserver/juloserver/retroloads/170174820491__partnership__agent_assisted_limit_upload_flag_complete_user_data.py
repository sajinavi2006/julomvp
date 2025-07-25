# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2023-12-05 03:50
from __future__ import unicode_literals

from django.db import migrations
from juloserver.julo.constants import FeatureNameConst
from juloserver.julo.models import FeatureSetting


def create_limitation_partnership_agent_assisted_uploader(app, _schema_editor):
    parameters = {
        'max_row' : 20,
    }

    FeatureSetting.objects.get_or_create(
        feature_name=FeatureNameConst.AGENT_ASSISTED_LIMIT_UPLOADER,
        is_active=True,
        parameters=parameters,
        category='partnership',
        description='Configure for limitation agent assisted uploader'
    )


class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.RunPython(
            create_limitation_partnership_agent_assisted_uploader,
            migrations.RunPython.noop
        ),
    ]
