# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import migrations
from juloserver.julo.constants import FeatureNameConst


from juloserver.julo.models import FeatureSetting



def create_collection_offer_general_website(apps, schema_editor):
    
    parameters = {
        'otp_wait_time_seconds': 300,
        'otp_max_request': 3,
        'otp_resend_time': 60
    }
    FeatureSetting.objects.create(
        feature_name=FeatureNameConst.COLLECTION_OFFER_GENERAL_WEBSITE,
        parameters=parameters,
        is_active=True,
        description="Sending otp to the general web page"
    )

class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.RunPython(create_collection_offer_general_website, migrations.RunPython.noop),
    ]
