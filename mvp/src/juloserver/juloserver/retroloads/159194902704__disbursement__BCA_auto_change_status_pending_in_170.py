# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import migrations
from juloserver.julo.constants import FeatureNameConst
from juloserver.julo.models import FeatureSetting


def add_bca_auto_change_status_pending_in_170(apps, schema_editor):
    FeatureSetting.objects.get_or_create(is_active=True,
        feature_name=FeatureNameConst.BCA_PENDING_STATUS_CHECK_IN_170,
        category="disbursement",
        parameters= {"max_retries": 6, "delay_in_hours": 4},
        description="auto change status pending in 170 to 180")


class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.RunPython(add_bca_auto_change_status_pending_in_170,
            migrations.RunPython.noop)
    ]
