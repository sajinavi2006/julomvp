# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import migrations
from juloserver.julo.constants import FeatureNameConst


from juloserver.julo.models import FeatureSetting



def force_to_high_creditscore(apps, schema_editor):
    
    FeatureSetting.objects.get_or_create(is_active=False,
        feature_name=FeatureNameConst.FORCE_HIGH_SCORE,
        category="credit_score",
        parameters=["email@example.com"],
        description="List email that will force to got score A-")


class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.RunPython(force_to_high_creditscore,
            migrations.RunPython.noop)
    ]
