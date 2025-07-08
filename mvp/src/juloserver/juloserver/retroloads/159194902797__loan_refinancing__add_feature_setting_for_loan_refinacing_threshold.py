# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import migrations, models


from juloserver.julo.models import FeatureSetting



def create_initial_threshold_for_customer_reliability(apps, schema_editor):
    
    FeatureSetting.objects.get_or_create(is_active=True,
                                         feature_name='loan_refinancing_threshold',
                                         parameters={
                                            'customer_reliability_threshold': 10
                                         },
                                         description="set threshold for loan refinancing")


class Migration(migrations.Migration):
    dependencies = [
    ]
