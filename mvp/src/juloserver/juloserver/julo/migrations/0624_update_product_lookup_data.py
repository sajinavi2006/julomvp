from __future__ import unicode_literals

from builtins import zip
import csv

from django.db import migrations
from django.db import transaction



def update_product_lookup_data(apps, _schema_editor):
    """"""
    ProductLookup = apps.get_model("julo", "ProductLookup")
    raw_data = [
        ['I.540-O.050-L.050-C1.010-C2.010-M', 0.54, 0.05, 0.05, 0, 0.01, True, 10, 1],
        ['I.660-O.050-L.050-C1.010-C2.010-M', 0.66, 0.05, 0.05, 0, 0.01, True, 10, 1],
        ['I.780-O.050-L.050-C1.010-C2.010-M', 0.78, 0.05, 0.05, 0, 0.01, True, 10, 1],
        ['I.540-O.050-L.050-C1.010-C2.010-M', 0.54, 0.05, 0.05, 0, 0.01, True, 11, 2],
        ['I.660-O.050-L.050-C1.010-C2.010-M', 0.66, 0.05, 0.05, 0, 0.01, True, 11, 2],
        ['I.780-O.050-L.050-C1.010-C2.010-M', 0.78, 0.05, 0.05, 0, 0.01, True, 11, 2],
    ]
    keys = [
        'product_name',
        'interest_rate',
        'origination_fee_pct',
        'late_fee_pct',
        'cashback_initial_pct',
        'cashback_payment_pct',
        'is_active',
        'product_line_id',
        'product_profile_id'
    ]

    for data in raw_data:
        check_existed = ProductLookup.objects.filter(product_name=data[0],
                                                     product_line_id=data[-2]).first()
        if not check_existed:
            ProductLookup.objects.create(**dict(list(zip(keys, data))))


class Migration(migrations.Migration):

    dependencies = [
        ('julo', '0623_retro_new_credit_matrix_data'),
    ]

    operations = [
        migrations.RunPython(update_product_lookup_data, migrations.RunPython.noop),
    ]
