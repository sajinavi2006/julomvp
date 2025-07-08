# -*- coding: utf-8 -*-
from __future__ import unicode_literals
from django.db import migrations

def add_address_fraud_prevention_feature(apps, schema_editor):
    MobileFeatureSetting = apps.get_model("julo", "MobileFeatureSetting")
    
    # add new feature settings
    MobileFeatureSetting.objects.create(
        feature_name="address_fraud_prevention",
        is_active=True
    )

class Migration(migrations.Migration):
    dependencies = [
    ]

    operations = [
        migrations.RunPython(add_address_fraud_prevention_feature, migrations.RunPython.noop),
    ]
