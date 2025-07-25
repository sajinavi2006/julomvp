# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2022-11-03 03:39
from __future__ import unicode_literals

from django.db import migrations

from juloserver.julo.models import SepulsaProduct
from juloserver.payment_point.constants import SepulsaProductCategory, SepulsaProductType

from juloserver.sdk.services import xls_to_dict


def add_pdam_sepulsa_product(apps, schema_editor):
    data = xls_to_dict('misc_files/excel/data_sepulsa_product_pdam.xlsx')

    product_list = data['PDAM']

    for idx, product in enumerate(product_list):
        product_id = product.get('product id', None)
        product_type = product.get('tipe produk',  None)
        area = product.get('area',  None)
        admin_charge = product.get('suggested admin fee\n(max admin charge per area)',  None)
        operator_code = product.get('operator code',  None)
        active = True if product['keterangan'] == 'OPEN' else False
        blocked = True if product['keterangan'] == 'OPEN' else False

        SepulsaProduct.objects.update_or_create(
            product_id=product_id,
            product_desc=operator_code,
            defaults=dict(
                product_name=area,
                product_label=product_type,
                category=SepulsaProductCategory.WATER_BILL,
                customer_price=0,
                customer_price_regular=0,
                admin_fee=admin_charge,
                service_fee=500,
                partner_price=500,
                type=SepulsaProductType.PDAM,
                is_active=active,
                is_not_blocked=blocked,
            )
        )

class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.RunPython(
            add_pdam_sepulsa_product, migrations.RunPython.noop
        ),
    ]
