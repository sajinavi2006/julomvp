# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import migrations
from juloserver.julo.constants import FeatureNameConst


from juloserver.julo.models import FeatureSetting



def add_auto_call_ping_138_settings(apps, schema_editor):
    
    FeatureSetting.objects.get_or_create(is_active=False,
                                        feature_name=FeatureNameConst.AUTO_CALL_PING_138,
                                        category="Temporary",
                                        parameters=None,
                                        description="auto call for 138 and auto change to 139 for call unanswered"
                                        )

class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.RunPython(add_auto_call_ping_138_settings, migrations.RunPython.noop)
    ]