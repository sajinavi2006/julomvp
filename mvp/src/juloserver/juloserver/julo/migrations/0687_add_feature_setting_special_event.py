# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import migrations
from juloserver.julo.constants import FeatureNameConst


def add_special_event_setting(apps, schema_editor):
    featuresetting = apps.get_model("julo", "FeatureSetting")
    parameters = {
        "max_age": 54,
        "min_age": None,
        "job_type": [
            "Pengusaha",
            "Freelance",
            "Ibu rumah tangga"
        ],
        "province": [
            "DI Yogyakarta",
            "Jawa Timur",
            "Bali",
            "Nusa Tenggara Barat (NTB)",
            "Nusa Tenggara Timur (NTT)"
        ],
        "job_industry": [
            "Design / Seni",
            "Entertainment / Event",
            "Media",
            "Pabrik / Gudang",
            "Perawatan Tubuh",
            "Perhotelan",
            "Staf Rumah Tangga",
            "Tehnik / Computer"
        ],
        "job_description": [
            "Design / Seni:All",
            "Entertainment / Event:All",
            "Media:All",
            "Pabrik / Gudang:All",
            "Perawatan Tubuh:All",
            "Perhotelan:All",
            "Staf Rumah Tangga:All",
            "Agen Perjalanan",
            "Buruh Pabrik / Gudang",
            "Customer Service",
            "Instruktur / Pembimbing Kursus",
            "Kebersihan",
            "Koki",
            "Mandor",
            "Pelayan / Pramuniaga",
            "Photographer",
            "Pilot / Staff Penerbangan",
            "Room Service / Pelayan",
            "Salesman",
            "Sewa Kendaraan",
            "SPG",
            "Supir",
            "Tukang Bangunan",
            "Tehnik / Computer:Warnet",
            "Tehnik / Computer:Otomotif"
        ]}

    description = "param for job industry, job description, job type, province, max age"
    special_event_setting = featuresetting.objects.update_or_create(
        feature_name=FeatureNameConst.SPECIAL_EVENT_BINARY
    )
    special_event_setting = special_event_setting[0]
    special_event_setting.parameters = parameters
    special_event_setting.is_active = True
    special_event_setting.description = description
    special_event_setting.save()

class Migration(migrations.Migration):

    dependencies = [
        ('julo', '0686_retroload_hsfb_configurations'),
    ]

    operations = [
        migrations.RunPython(add_special_event_setting, migrations.RunPython.noop),
    ]

