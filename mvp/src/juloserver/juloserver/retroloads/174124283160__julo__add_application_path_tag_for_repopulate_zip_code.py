# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2025-03-06 06:33
from __future__ import unicode_literals

from django.db import migrations
from juloserver.application_flow.models import (
    ApplicationTag,
    ApplicationPathTagStatus,
)
from juloserver.application_form.constants import SimilarityTextConst


def execute(apps, schema_editor):

    tag = SimilarityTextConst.IS_CHECKED_REPOPULATE_ZIPCODE
    if not ApplicationTag.objects.filter(application_tag=tag).exists():
        ApplicationTag.objects.create(
            application_tag=tag,
            is_active=True,
        )
        ApplicationPathTagStatus.objects.create(application_tag=tag, status=0, definition='failed')


class Migration(migrations.Migration):

    dependencies = []

    operations = [
        migrations.RunPython(execute, migrations.RunPython.noop),
    ]
