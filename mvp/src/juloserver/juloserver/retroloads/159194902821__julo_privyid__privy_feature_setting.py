# -*- coding: utf-8 -*-
from __future__ import unicode_literals
from django.db import migrations

from juloserver.julo.models import MobileFeatureSetting


def update_feature(apps, schema_editor):
    

    # add new feature settings
    MobileFeatureSetting.objects.create(
        feature_name="privy_mode",
        is_active=False
    )

    # edit feature setting failover
    failover = MobileFeatureSetting.objects.filter(
        feature_name='failover_digisign').last()
    if failover:
        failover.feature_name='digital_signature_failover'
        failover.save()

class Migration(migrations.Migration):
    dependencies = [
    ]

    operations = [
        migrations.RunPython(update_feature, migrations.RunPython.noop),
    ]
