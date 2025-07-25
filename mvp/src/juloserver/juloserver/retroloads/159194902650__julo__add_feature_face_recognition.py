# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2019-12-24 08:01
from __future__ import unicode_literals

from django.conf import settings
import django.core.validators
from django.db import migrations, models
import django.db.models.deletion
import juloserver.julo.models
from juloserver.julo.constants import FeatureNameConst
from juloserver.julo.models import FeatureSetting

class Migration(migrations.Migration):


    def add_face_recognition(apps, schema_editor):
        
        FeatureSetting.objects.get_or_create(is_active=True,
                                             feature_name=FeatureNameConst.FACE_RECOGNITION,
                                             parameters={
                                                 'alert_notification_through_slack': {
                                                     'is_active': True,
                                                     'users': ['UMFHYCUGH', 'U2M1DBAQ2', 'UKZC8UE2H', 'U5ND8AZBM',
                                                               'UFZ7RDCQK']
                                                 },
                                             },
                                             description="face recognition setting"
                                             )

    dependencies = [
    ]

    operations = [
        migrations.RunPython(add_face_recognition)
    ]
