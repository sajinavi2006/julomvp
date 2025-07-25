# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2020-09-11 08:33
from __future__ import unicode_literals

import django.contrib.postgres.fields.jsonb
from django.db import migrations, models

from juloserver.julo.models import FeatureSetting, MobileFeatureSetting
from juloserver.julo.constants import FeatureNameConst


def add_ocr_feature_setting(apps, _schema_editor):
    MobileFeatureSetting.objects.get_or_create(
        is_active=True,
        feature_name="opencv_setting",
        parameters={
            "number_of_tries": 3,
            "blur": {
                "threshold": 130
            },
            "glare": {
                "threshold": 230,
                "percentage_limit": 0.1
            },
            "dark": {
                "numer_of_bin": 8,
                "lower_bin": 3,
                "upper_bin": 6,
                "lower_limit": 30,
                "upper_limit": 10
            }
        })

    ocr_setting, _status = FeatureSetting.objects.get_or_create(
        feature_name=FeatureNameConst.OCR_SETTING,
        category="ocr",
    )

    ocr_setting.is_active = True
    ocr_setting.parameters = {
        "object_detection":{
            "num_classes":11,
            "assume_times":0,
            "score_threshold":0.62,
            "minimum_personal_info":3
        },
        "text_recognition":{
            'bbox_overlap_thres':{
                'nik':0.5,
                'nama':0.5,
                'jenis_kelamin':0.5,
                'tempat_tanggal_lahir':0.5,
                'provinsi':0.5,
                'kabupaten':0.5,
                'alamat':0.5,
                'rt_rw':0.5,
                'kelurahan':0.5,
                'kecamatan':0.5,
                'berlaku_hingga':0.5
            },
            'ocr_confidence_thres':{
                'nik':{
                    'thresh_value':0.6,
                    'thresh_count':1
                },
                'nama':{
                    'thresh_value':0.45,
                    'thresh_count':3
                },
                'jenis_kelamin':{
                    'thresh_value':0.1,
                    'thresh_count':5
                },
                'tempat_tanggal_lahir':{
                    'pob':{
                        'thresh_value':0.1,
                        'thresh_count':5
                    },
                    'dob':{
                        'thresh_value':0.1,
                        'thresh_count':5
                    },
                },
                'provinsi':{
                    'thresh_value':0.45,
                    'thresh_count':4
                },
                'kabupaten':{
                    'thresh_value':0.35,
                    'thresh_count':3
                },
                'alamat':{
                    'thresh_value':0.98,
                    'thresh_count':3
                },
                'rt_rw':{
                    'thresh_value':0.35,
                    'thresh_count':5
                },
                'kelurahan':{
                    'thresh_value':0.65,
                    'thresh_count':4
                },
                'kecamatan':{
                    'thresh_value':0.4,
                    'thresh_count':4
                },
                'berlaku_hingga':{
                    'thresh_value':0.1,
                    'thresh_count':3
                }
            }
        }
    }
    ocr_setting.save()


class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.RunPython(add_ocr_feature_setting, migrations.RunPython.noop),
    ]
