# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2016-06-24 01:19
from __future__ import unicode_literals

from django.db import migrations


from juloserver.julo.models import ProductLookup

from juloserver.julo.product_lines import ProductLines, ProductLineCodes

from juloserver.julo.models import ProductLine


def load_product_lines(apps, schema_editor):
    product_lines = ProductLines

    for pl in product_lines:
        if pl.product_line_code > ProductLineCodes.GRAB2:
            continue
        kwargs = {
            'product_line_code': pl.product_line_code,
            'product_line_type': pl.product_line_type,
            'min_amount': pl.min_amount,
            'max_amount': pl.max_amount,
            'min_duration': pl.min_duration,
            'max_duration': pl.max_duration,
            'min_interest_rate': pl.min_interest_rate,
            'max_interest_rate': pl.max_interest_rate,
            'payment_frequency': pl.payment_frequency,
        }
        product_line = ProductLine(**kwargs)
        product_line.save()

def load_product_lookups(apps, schema_editor):
    product_lookups = [

        (1, 'I.180-O.050-L.050-C1.010-C2.010-M', 0.180, 0.050, 0.050, 0.010, 0.010, 'Monthly', True),
        (2, 'I.210-O.050-L.050-C1.010-C2.010-M', 0.210, 0.050, 0.050, 0.010, 0.010, 'Monthly', True),
        (3, 'I.240-O.050-L.050-C1.010-C2.010-M', 0.240, 0.050, 0.050, 0.010, 0.010, 'Monthly', True),
        (4, 'I.270-O.050-L.050-C1.010-C2.010-M', 0.270, 0.050, 0.050, 0.010, 0.010, 'Monthly', True),
        (5, 'I.300-O.050-L.050-C1.010-C2.010-M', 0.300, 0.050, 0.050, 0.010, 0.010, 'Monthly', True),
        (6, 'I.330-O.050-L.050-C1.010-C2.010-M', 0.330, 0.050, 0.050, 0.010, 0.010, 'Monthly', True),
        (7, 'I.360-O.050-L.050-C1.010-C2.010-M', 0.360, 0.050, 0.050, 0.010, 0.010, 'Monthly', True),
        (8, 'I.390-O.050-L.050-C1.010-C2.010-M', 0.390, 0.050, 0.050, 0.010, 0.010, 'Monthly', True),
        (9, 'I.420-O.050-L.050-C1.010-C2.010-M', 0.420, 0.050, 0.050, 0.010, 0.010, 'Monthly', True),
        (10, 'I.450-O.050-L.050-C1.010-C2.010-M', 0.450, 0.050, 0.050, 0.010, 0.010, 'Monthly', True),
        (11, 'I.480-O.050-L.050-C1.010-C2.010-M', 0.480, 0.050, 0.050, 0.010, 0.010, 'Monthly', True),

    ]

    
    for pl in product_lookups:
        kwargs = {
            'product_code': pl[0],
            'product_name': pl[1],
            'interest_rate': pl[2],
            'origination_fee_pct': pl[3],
            'late_fee_pct': pl[4],
            'cashback_initial_pct': pl[5],
            'cashback_payment_pct': pl[6],
            'is_active': pl[8],
            'product_line_id': 10,
        }
        product_lookup = ProductLookup(**kwargs)
        product_lookup.save()


class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.RunPython(load_product_lines),
        migrations.RunPython(load_product_lookups),
    ]
