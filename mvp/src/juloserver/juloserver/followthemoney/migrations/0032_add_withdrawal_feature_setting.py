# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import migrations
from juloserver.julo.constants import FeatureNameConst


def add_withdrawal_feature_settings(apps, schema_editor):
    FeatureSetting = apps.get_model("julo", "FeatureSetting")
    featuer_obj = FeatureSetting.objects.get_or_create(
        is_active=True,
        feature_name=FeatureNameConst.XFERS_WITHDRAWAL,
        category="withdrawal",
        description="automatic withdraw via xfers api"
    )


class Migration(migrations.Migration):

    dependencies = [
        ('followthemoney', '0031_add_index_loan_writeoff'),
    ]

    operations = [
        migrations.RunPython(add_withdrawal_feature_settings,
            migrations.RunPython.noop)
    ]
