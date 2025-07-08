# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import migrations
from juloserver.julo.constants import FeatureNameConst


from juloserver.julo.models import FeatureSetting



def add_sent_email_and_tracking_feature(apps, schema_editor):
    
    FeatureSetting.objects.get_or_create(is_active=True,
                                        feature_name=FeatureNameConst.SENT_EMAIl_AND_TRACKING,
                                        category="Streamlined Communication",
                                        parameters=None,
                                        description="auto call for 138 and auto change to 139 for call unanswered"
                                        )

class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.RunPython(add_sent_email_and_tracking_feature, migrations.RunPython.noop)
    ]