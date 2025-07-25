# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2020-11-30 15:03
from __future__ import unicode_literals

from django.db import migrations
from juloserver.julo.models import FeatureSetting


def add_feature_settings_reupload(apps, _schema_editor):
    FeatureSetting.objects.create(
        feature_name="privy_reupload_settings",
        is_active=True,
        parameters=dict(
            KTP_CODES=['PRVK002', 'PRVK003', 'PRVK004', 'PRVK013', 'PRVD001',
                       'PRVD002', 'PRVD005', 'PRVK019', 'PRVK016'],
            E_KTP_CODES=['PRVP010'],
            SELFIE_CODES=['PRVS001', 'PRVS003', 'PRVS004', 'PRVS006', 'PRVD001', 'PRVD011',
                          'PRVD002', 'PRVD005', 'PRVD013', 'PRVD007',
                          'PRVD009', 'PRVRD001', 'PRVRD002', 'PRVRD003'],
            SELFIE_WITH_KTP_CODES=['PRVS002', 'PRVP006', 'PRVP014'],
            DRIVER_LICENSE_CODES=['PRVK011', 'PRVK012', 'PRVP004', 'PRVP005', 'PRVK017',
                                  'PRVP012', 'PRVP015', 'PRVD013', 'PRVK006', 'PRVK016'],
            KK_CODES=['PRVK009', 'PRVK015', 'PRVK018', 'PRVN004', 'PRVP001', 'PRVD007', 'PRVD011',
                      'PRVP002', 'PRVP003', 'PRVK008',
                      'PRVK019', 'PRVK017', 'PRVD009'],
            REJECTED_CODES=['PRVK001', 'PRVK014', 'PRVM002', 'PRVM001', 'PRVM003',
                            'PRVN002', 'PRVD004', 'PRVP009'],
            PASSPORT=['PRVR001', 'PRVR002', 'PRVR003', 'PRVR004', 'PRVR005', 'PRVR006',
                      'PRVRD001', 'PRVRD002', 'PRVRD003', 'PRVRS002'],
            PASSPORT_SELFIE=['PRVRS002']
        )
    )

class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.RunPython(add_feature_settings_reupload, migrations.RunPython.noop)
    ]
