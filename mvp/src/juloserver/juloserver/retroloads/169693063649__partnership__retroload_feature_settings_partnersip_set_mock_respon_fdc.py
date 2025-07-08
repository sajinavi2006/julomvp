# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.conf import settings
from django.db import migrations
import datetime

from juloserver.julo.constants import FeatureNameConst

from juloserver.julo.models import FeatureSetting


def mocking_partnership_fdc_result_feature_setting(apps, _schema_editor):
    if settings.ENVIRONMENT == "prod":
        return

    fdc_response = {
        "inquiryReason": "1 - Applying loan via Platform",
        "status": "Found",
        "inquiryDate": datetime.datetime.now().strftime ("%Y-%m-%d %H:%M:%S"),
        "pinjaman": [
            {
                "dpd_max": 20,
                "dpd_terakhir": 0,
                "id_penyelenggara": 63,
                "jenis_pengguna_ket": "Individual",
                "kualitas_pinjaman_ket": "Lancar (<30 hari)",
                "nama_borrower": "Herti Novianti",
                "nilai_pendanaan": 5000000,
                "no_identitas": 3275026708810040,
                "no_npwp": 674718820432000,
                "sisa_pinjaman_berjalan": 0,
                "status_pinjaman_ket": "Fully Paid",
                "penyelesaian_w_oleh": "Mocking Data",
                "pendanaan_syariah": False,
                "tipe_pinjaman": "Multiguna",
                "sub_tipe_pinjaman": "Onetime Loan / Cash Loan",
                "id": "5dc67af8c3b24fb01e3cc7135b8ffd45",
                "reference": "",
                "tgl_jatuh_tempo_pinjaman": datetime.datetime.now().strftime ("%Y-%m-%d"),
                "tgl_pelaporan_data": datetime.datetime.now().strftime ("%Y-%m-%d"),
                "tgl_penyaluran_dana": datetime.datetime.now().strftime ("%Y-%m-%d"),
                "tgl_perjanjian_borrower": datetime.datetime.now().strftime ("%Y-%m-%d"),
            },
        ]

    }

    FeatureSetting.objects.get_or_create(
        is_active=False,
        feature_name=FeatureNameConst.PARTNERSHIP_FDC_MOCK_RESPONSE_SET,
        category="mocking_response",
        parameters={
          "product": ["dana",],
          "latency": 1000,
          "response_value": fdc_response,
        },
        description="Config FDC mocking response"
    )


class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.RunPython(mocking_partnership_fdc_result_feature_setting, migrations.RunPython.noop)
    ]
