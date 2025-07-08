# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import migrations
from django.utils import timezone
from datetime import datetime


def add_fdc_feature_setting(apps, _schema_editor):
    FeatureSetting = apps.get_model("julo", "FeatureSetting")
    FeatureSetting.objects.get_or_create(is_active=True,
        feature_name="fdc_configuration",
        category="fdc",
        parameters= {'application_process':True, 'outstanding_loan':True},
        description="FeatureSettings to turn on/off FDC inquiry at Application status 100 and LoanStatus 232")



class Migration(migrations.Migration):
    dependencies = [
        ('julo', '0601_add_field_fdc_inquiry_loan'),
    ]

    operations = [
        migrations.RunPython(add_fdc_feature_setting, migrations.RunPython.noop)
    ]