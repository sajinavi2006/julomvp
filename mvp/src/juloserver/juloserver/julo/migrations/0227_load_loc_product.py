# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2018-04-06 13:53
from __future__ import unicode_literals

from django.db import migrations, models
from juloserver.portal.object.product_profile.services import generate_product_lookup


LOC_PRODUCT = {
    'code': 60,
    'name': 'LOC',
    'min_amount': 300000,
    'max_amount': 300000,
    'min_duration': 1,
    'max_duration': 1,
    'min_interest_rate': 0.00,
    'max_interest_rate': 0.00,
    'interest_rate_increment': 0.00,
    'min_origination_fee': 0.00,
    'max_origination_fee': 0.00,
    'origination_fee_increment': 0.00,
    'cashback_initial': 0.00,
    'cashback_payment': 0.00,
    'late_fee': 0.00,
    'payment_frequency': 'Monthly',
    'debt_income_ratio': None,
    'is_initial': True,
    'is_active': True
}

LOC_CUSTOMER = {
     'credit_score': ['A-', 'B+', 'B-']
}


def load_loc_product(apps, schema_editor):
    ProductLine = apps.get_model("julo", "ProductLine")
    ProductLookup = apps.get_model("julo", "ProductLookup")
    ProductProfile = apps.get_model("julo", "ProductProfile")
    ProductCustomerCriteria = apps.get_model("julo", "ProductCustomerCriteria")

    product_profile = ProductProfile(**LOC_PRODUCT)
    product_profile.save()

    # loc customer criteria
    LOC_CUSTOMER['product_profile'] = product_profile
    product_customer_criteria = ProductCustomerCriteria(**LOC_CUSTOMER)
    product_customer_criteria.save()

    # loc product_line
    product_line = ProductLine.objects.create(
        product_line_code=product_profile.code,
        product_line_type=product_profile.name,
        min_amount=product_profile.min_amount,
        max_amount=product_profile.max_amount,
        min_duration=product_profile.min_duration,
        max_duration=product_profile.max_duration,
        min_interest_rate=product_profile.min_interest_rate,
        max_interest_rate=product_profile.max_interest_rate,
        payment_frequency=product_profile.payment_frequency,
        product_profile=product_profile
    )

    # product lookup
    product_lookup_list = generate_product_lookup(product_profile, product_line)
    for product_lookup_data in product_lookup_list:
        product_lookup = ProductLookup(**product_lookup_data)
        product_lookup.save()

class Migration(migrations.Migration):

    dependencies = [
        ('julo', '0226_sepulsa_integrate'),
    ]

    operations = [
        migrations.RunPython(load_loc_product, migrations.RunPython.noop),
    ]

