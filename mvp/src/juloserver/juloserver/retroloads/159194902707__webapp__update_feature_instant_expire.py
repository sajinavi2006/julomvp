# -*- coding: utf-8 -*-
from __future__ import unicode_literals
from django.db import migrations

from juloserver.julo.models import FeatureSetting


def update_feature(apps, schema_editor):
    
    FeatureSetting.objects.create(
        feature_name="instant_expiration_web_application",
        is_active=False,
        description="Instant Expiration Web Application API"
    )

class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.RunPython(update_feature, migrations.RunPython.noop),
    ]
