# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2021-03-22 00:12
from __future__ import unicode_literals

from django.db import migrations
from django.conf import settings

from juloserver.ecommerce.models import EcommerceConfiguration, EcommerceBankConfiguration
from juloserver.julo.models import Bank

ECOMMERCE_CONFIGURATION_DATA = [
    {
        'ecommerce_name': 'Tokopedia',
        'selection_logo': '{}tokopedia/tokopedia_selection_logo.png'.format(
            settings.ECOMMERCE_LOGO_STATIC_FILE_PATH
        ),
        'background_logo': '{}tokopedia/tokopedia_background_logo.png'.format(
            settings.ECOMMERCE_LOGO_STATIC_FILE_PATH
        ),
        'color_scheme': '#60bb55',
        'url': 'https://www.tokopedia.com/',
        'text_logo': '{}tokopedia/tokopedia_text_logo.png'.format(
            settings.ECOMMERCE_LOGO_STATIC_FILE_PATH
        ),
        'bank_list': [
            {
                'bank_code': 'BNI',
                'prefix': ['82770']
            },
            {
                'bank_code': 'CIMB_NIAGA',
                'prefix': ['64490']
            },
        ],
    },
    {
        'ecommerce_name': 'Shopee',
        'selection_logo': '{}shopee/shopee_selection_logo.png'.format(
            settings.ECOMMERCE_LOGO_STATIC_FILE_PATH
        ),
        'background_logo': '{}shopee/shopee_background_logo.png'.format(
            settings.ECOMMERCE_LOGO_STATIC_FILE_PATH
        ),
        'color_scheme': '#ea501f',
        'url': 'https://shopee.co.id/',
        'text_logo': '{}shopee/shopee_text_logo.png'.format(
            settings.ECOMMERCE_LOGO_STATIC_FILE_PATH
        ),
        'bank_list': [
            {
                'bank_code': 'MANDIRI',
                'prefix': ['89608']
            },
        ],
    },
    {
        'ecommerce_name': 'Lazada',
        'selection_logo': '{}lazada/lazada_selection_logo.png'.format(
            settings.ECOMMERCE_LOGO_STATIC_FILE_PATH
        ),
        'background_logo': '{}lazada/lazada_background_logo.png'.format(
            settings.ECOMMERCE_LOGO_STATIC_FILE_PATH
        ),
        'color_scheme': '#ed661e',
        'url': 'https://www.lazada.co.id/',
        'text_logo': '{}lazada/lazada_text_logo.png'.format(
            settings.ECOMMERCE_LOGO_STATIC_FILE_PATH
        ),
        'bank_list': [
            {
                'bank_code': 'BNI',
                'prefix': ['82828']
            },
        ],
    },
    {
        'ecommerce_name': 'Bukalapak',
        'selection_logo': '{}bukalapak/bukalapak_selection_logo.png'.format(
            settings.ECOMMERCE_LOGO_STATIC_FILE_PATH
        ),
        'background_logo': '{}bukalapak/bukalapak_background_logo.png'.format(
            settings.ECOMMERCE_LOGO_STATIC_FILE_PATH
        ),
        'color_scheme': '#e20d4d',
        'url': 'https://www.bukalapak.com/',
        'text_logo': '{}bukalapak/bukalapak_text_logo.png'.format(
            settings.ECOMMERCE_LOGO_STATIC_FILE_PATH
        ),
        'bank_list': [
            {
                'bank_code': 'BNI',
                'prefix': ['8608']
            },
            {
                'bank_code': 'CIMB_NIAGA',
                'prefix': ['9669']
            },
        ],
    },
    {
        'ecommerce_name': 'Blibli',
        'selection_logo': '{}blibli/blibli_selection_logo.png'.format(
            settings.ECOMMERCE_LOGO_STATIC_FILE_PATH
        ),
        'background_logo': '{}blibli/blibli_background_logo.png'.format(
            settings.ECOMMERCE_LOGO_STATIC_FILE_PATH
        ),
        'color_scheme': '#268acb',
        'url': 'https://www.blibli.com/',
        'text_logo': '{}blibli/blibli_text_logo.png'.format(
            settings.ECOMMERCE_LOGO_STATIC_FILE_PATH
        ),
        'bank_list': [
            {
                'bank_code': 'BNI',
                'prefix': ['87071']
            },
        ],
    },
]


def data_seed_for_ecommerce_configuration(app, schema_editor):
    for data in ECOMMERCE_CONFIGURATION_DATA:
        ecommerce_configuration, _ = EcommerceConfiguration.objects.get_or_create(
            ecommerce_name=data['ecommerce_name'],
            selection_logo=data['selection_logo'],
            background_logo=data['background_logo'],
            color_scheme=data['color_scheme'],
            url=data['url'],
            text_logo=data['text_logo'],
        )
        for bank_data in data['bank_list']:
            bank = Bank.objects.filter(xfers_bank_code=bank_data['bank_code']).last()
            if bank:
                EcommerceBankConfiguration.objects.get_or_create(
                    ecommerce_configuration_id=ecommerce_configuration.id,
                    bank_id=bank.id,
                    prefix=bank_data['prefix']
                )


class Migration(migrations.Migration):
    dependencies = [
    ]

    operations = [
        migrations.RunPython(data_seed_for_ecommerce_configuration, migrations.RunPython.noop),
    ]
