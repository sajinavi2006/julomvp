# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2023-08-04 04:04
from __future__ import unicode_literals

from django.db import migrations

from django.conf import settings

from juloserver.ecommerce.constants import CategoryType
from juloserver.ecommerce.models import EcommerceConfiguration, EcommerceBankConfiguration
from juloserver.julo.banks import XfersBankCode
from juloserver.julo.models import Bank


def add_indogold_to_ecommerce_configuration(apps, _schema_editor):
    indogold_config, _ = EcommerceConfiguration.objects.get_or_create(
        ecommerce_name='IndoGold',
    )

    base_url = settings.ECOMMERCE_LOGO_STATIC_FILE_PATH
    updated_info = {
        'selection_logo': f"{base_url}indogold/indogold_selection_logo.png",
        'background_logo': f"{base_url}indogold/indogold_background_logo.png",
        'text_logo': f"{base_url}indogold/indogold_text_logo.png",
        'url': "https://www.indogold.id/",
        'color_scheme': '#F9C41D',
        'order_number': 7,
        'category_type': CategoryType.ECOMMERCE,
    }
    indogold_config.update_safely(**updated_info)

    mapping_xfers_bank_code_to_list_prefix = {
        XfersBankCode.DANAMON: ['7915'],
        XfersBankCode.CIMB_NIAGA: ['5919'],
        XfersBankCode.MAYBANK: ['7812'],
        XfersBankCode.HANA: ['9772'],
        XfersBankCode.MANDIRI: ['70014'],
        XfersBankCode.BRI: ['88788'],
        XfersBankCode.PERMATA: ['8778'],
        XfersBankCode.PERMATA_UUS: ['8624'],
        XfersBankCode.BNI: ['8578'],
        # XfersBankCode.BNC: ['99202'],
        XfersBankCode.DKI: ['995014'],
        XfersBankCode.BJB: ['1887']
    }
    for xfers_bank_code, list_prefix in mapping_xfers_bank_code_to_list_prefix.items():
        EcommerceBankConfiguration.objects.get_or_create(
            ecommerce_configuration_id=indogold_config.id,
            bank_id=Bank.objects.get(xfers_bank_code=xfers_bank_code).id,
            prefix=list_prefix
        )


class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.RunPython(add_indogold_to_ecommerce_configuration, migrations.RunPython.noop)
    ]
