# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import migrations, models

def add_available_balance_mock(apps, schema_editor):
    FeatureSetting = apps.get_model("julo", "FeatureSetting")
    FeatureSetting.objects.get_or_create(is_active=True,
                                         feature_name='mock_available_balance',
                                         parameters={
                                            'available_balance': 50000000
                                         },
                                         description="mock available balance for xfers")

class Migration(migrations.Migration):
    dependencies = [
        ('followthemoney', '0025_retroload_lla_new_template'),
    ]

    operations = [
        migrations.RunPython(add_available_balance_mock)
    ]
