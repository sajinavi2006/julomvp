# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import migrations
from juloserver.julo.constants import FeatureNameConst


def add_sms_activation_paylater_feature_settings(apps, schema_editor):
    FeatureSetting = apps.get_model("julo", "FeatureSetting")
    FeatureSetting.objects.get_or_create(is_active=True,
                                         feature_name=FeatureNameConst.SMS_ACTIVATION_PAYLATER,
                                         )


class Migration(migrations.Migration):

    dependencies = [
        ('paylater', '0045_initdata_bukalapakinterest'),
    ]

    operations = [
        migrations.RunPython(add_sms_activation_paylater_feature_settings,
            migrations.RunPython.noop)
    ]
