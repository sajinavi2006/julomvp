# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import migrations, models

from juloserver.julo.models import FeatureSetting


def add_available_balance_mock(apps, schema_editor):
    
    FeatureSetting.objects.get_or_create(is_active=True,
                                         feature_name='mock_available_balance',
                                         parameters={
                                            'available_balance': 50000000
                                         },
                                         description="mock available balance for xfers")

class Migration(migrations.Migration):
    dependencies = [
    ]

    operations = [
        migrations.RunPython(add_available_balance_mock)
    ]
