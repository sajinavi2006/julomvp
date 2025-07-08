from __future__ import unicode_literals

from django.db import migrations
from juloserver.julo.constants import FeatureNameConst
from juloserver.julo.models import FeatureSetting
from django.conf import settings

BUCKET_URL = settings.STATIC_ALICLOUD_BUCKET_URL + 'signatures/'

def create_feature_settings_list_lender_signature_images(apps, _schema_editor):
    parameters = {
        'lenders': {
            'jtp': {
                'signature': BUCKET_URL + 'jtp.png',
                'poc_name': 'Thadea Silvana',
                'poc_position': 'Direktur PT Julo Teknologi Perdana',
                'license_no': '9120008631626',
                'address': 'Eightyeight@kasablanka office tower Lt. 10 Unit E, Jl. Casablanca Raya Kav. 88, Menteng Dalam, Tebet, DKI Jakarta'
            },
            'jh': {
                'signature': BUCKET_URL + 'jh.png',
                'poc_name': 'Hans Sebastian',
                'poc_position': 'Direktur Julo Holding Pte. Ltd',
                'license_no': '201809592H',
                'address': '1 Raffles Place, One Raffles Place Singapore'
            },
            'pascal': {
                'signature': BUCKET_URL + 'pascal.png',
                'poc_name': 'Hans Sebastian',
                'poc_position': 'Direktur Pascal International Pte. Ltd.',
                'license_no': '202116624E',
                'address': '6 Battery Road, Singapore'
            },
        },
        'director': {
            'signature': BUCKET_URL + 'jtf.png',
            'poc_name': 'Gharnis Athe M. Ginting',
            'poc_position': 'Kuasa Direktur'
        }
    }
    FeatureSetting.objects.create(
        feature_name=FeatureNameConst.LIST_LENDER_INFO,
        parameters=parameters,
        is_active=True,
        category='signature',
        description="List information about Lender for creating P3 content"
    )


class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.RunPython(create_feature_settings_list_lender_signature_images, migrations.RunPython.noop)
    ]
