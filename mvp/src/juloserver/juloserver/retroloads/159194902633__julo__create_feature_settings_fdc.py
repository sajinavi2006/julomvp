# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import migrations
from django.utils import timezone
from datetime import datetime


from juloserver.julo.models import FeatureSetting



def add_fdc_feature_setting(apps, _schema_editor):
    
    FeatureSetting.objects.get_or_create(is_active=True,
        feature_name="fdc_configuration",
        category="fdc",
        parameters= {'application_process':True, 'outstanding_loan':True},
        description="FeatureSettings to turn on/off FDC inquiry at Application status 100 and LoanStatus 232")



class Migration(migrations.Migration):
    dependencies = [
    ]

    operations = [
        migrations.RunPython(add_fdc_feature_setting, migrations.RunPython.noop)
    ]