# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import migrations


from juloserver.julo.models import MobileFeatureSetting



def create_form_selfie_mobile_setting(apps, schema_editor):
    
    setting = MobileFeatureSetting(
        feature_name="form_selfie",
        parameters={},
    )
    setting.save()


class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.RunPython(create_form_selfie_mobile_setting),
    ]
