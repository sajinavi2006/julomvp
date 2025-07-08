# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import migrations
from juloserver.julo.constants import FeatureNameConst


def rename_suspend_account_feature_settings(apps, schema_editor):
    FeatureSetting = apps.get_model("julo", "FeatureSetting")
    feature_setting = FeatureSetting.objects.filter(feature_name="suspend_account_paylater").last()
    if feature_setting:
        feature_setting.feature_name = FeatureNameConst.SUSPEND_ACCOUNT_PAYLATER
        feature_setting.save()


class Migration(migrations.Migration):

    dependencies = [
        ('paylater', '0048_index_invoice_number_partner_transaction'),
    ]

    operations = [
        migrations.RunPython(rename_suspend_account_feature_settings,
                             migrations.RunPython.noop)
    ]
