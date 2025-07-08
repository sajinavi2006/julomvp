from __future__ import unicode_literals

from django.db import migrations
from juloserver.julo.constants import FeatureNameConst
from juloserver.julo.models import FeatureSetting


def create_feature_settings_cross_selling_config(apps, _schema_editor):
    parameters = {
        'cross_selling_message': "Ada yang perlu dibeli atau dibayar? Sekalian aja!",
        'available_limit_image': "https://statics.julo.co.id/loan/available_limit.png",
        'number_of_products': 3,
        'info': {
            1: {"message": "Cairkan dana tunai kapan dan di mana aja!", "deeplink": "julo://product_transfer_self"},
            2: {"message": "Lebih gampang kirim uang ke orang tersayang!", "deeplink": "julo://nav_inapp_product_transfer_other"},
            3: {"message": "Tinggal pilih berapa nominal atau GB!", "deeplink": "julo://pulsa_data"},
            4: {"message": "Bayar tagihan, komunikasi bisa jalan terus!", "deeplink": "julo://kartu_pasca_bayar"},
            5: {"message": "Isi saldo cepat, bayarnya nanti!", "deeplink": "julo://e-wallet"},
            6: {"message": "Bayar tangihan/ beli token sebelum padam!", "deeplink": "julo://listrik_pln"},
            7: {"message": "Bayar tagihan, berobat gak pake terhambat!", "deeplink": "julo://bpjs_kesehatan"},
            8: {"message": "Belanja di e-commerce, bayar lewat JULO aja!", "deeplink": "julo://e-commerce"},
            11: {"message": "Beli tiket nyaman, bayarnya ntar aja abis gajian!", "deeplink": "julo://train_ticket"},
            12: {"message": "Bayar tagihan, air mengalir lancar dari keran!", "deeplink": "julo://pdam_home_page"},
            13: {"message": "Tagihan terbayar, belajar tenang!", "deeplink": "julo://education_spp"},
            15: {"message": "Tagihan terbayar, berobat tenang!", "deeplink": "julo://healthcare_main_page"},
            19: {"message": "Transaksi jadi lebih sat set, tinggal scan!", "deeplink": "julo://qris_main_page"}
        },
        'products': [
            {'priority': 1, 'method': 5, 'minimum_limit': 100000, 'is_locked': False},
            {'priority': 2, 'method': 3, 'minimum_limit': 100000, 'is_locked': True},
            {'priority': 3, 'method': 8, 'minimum_limit': 300000, 'is_locked': True},
            {'priority': 4, 'method': 1, 'minimum_limit': 300000, 'is_locked': False},
            {'priority': 5, 'method': 6, 'minimum_limit': 100000, 'is_locked': False},
            {'priority': 6, 'method': 12, 'minimum_limit': 50000, 'is_locked': False}
        ]
    }
    FeatureSetting.objects.get_or_create(
         feature_name=FeatureNameConst.CROSS_SELLING_CONFIG,
         parameters=parameters,
         category='loan',
         is_active=False
    )


class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.RunPython(create_feature_settings_cross_selling_config, migrations.RunPython.noop)
    ]
