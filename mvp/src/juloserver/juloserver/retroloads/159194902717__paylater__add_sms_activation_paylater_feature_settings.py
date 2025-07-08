# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import migrations
from juloserver.julo.constants import FeatureNameConst


from juloserver.julo.models import FeatureSetting



def add_sms_activation_paylater_feature_settings(apps, schema_editor):
    
    FeatureSetting.objects.get_or_create(is_active=True,
                                         feature_name=FeatureNameConst.SMS_ACTIVATION_PAYLATER,
                                         )


class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.RunPython(add_sms_activation_paylater_feature_settings,
            migrations.RunPython.noop)
    ]
