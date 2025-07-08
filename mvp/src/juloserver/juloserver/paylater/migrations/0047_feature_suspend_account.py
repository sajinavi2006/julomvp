# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import migrations
from juloserver.julo.constants import FeatureNameConst


def suspend_account_feature_settings(apps, schema_editor):
    FeatureSetting = apps.get_model("julo", "FeatureSetting")
    parameters = dict(suspend_delay=1)
    FeatureSetting.objects.get_or_create(is_active=False,
                                         feature_name=FeatureNameConst.SUSPEND_ACCOUNT_PAYLATER,
                                         parameters=parameters,
                                         category="paylater",
                                         description="Delay time before suspend account paylater"
                                         )


class Migration(migrations.Migration):

    dependencies = [
        ('paylater', '0046_add_sms_activation_paylater_feature_settings'),
    ]

    operations = [
        migrations.RunPython(suspend_account_feature_settings,
                             migrations.RunPython.noop)
    ]
