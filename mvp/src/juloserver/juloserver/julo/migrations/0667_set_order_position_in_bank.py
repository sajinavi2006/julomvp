# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import migrations


def add_order_position(apps, _schema_editor):
    xfers_code_bank_list = ('BCA', 'MANDIRI', 'BRI', 'BNI', 'CIMB_NIAGA', 'PERMATA')
    Bank = apps.get_model("julo", "Bank")
    order_position = 1
    for xfers_code in xfers_code_bank_list:
        bank_to_add_order_position = Bank.objects.get(xfers_bank_code=xfers_code)
        if bank_to_add_order_position:
            bank_to_add_order_position.order_position = order_position
            bank_to_add_order_position.save()
            order_position += 1

class Migration(migrations.Migration):

    dependencies = [
        ('julo', '0666_add_order_position_in_bank'),
    ]

    operations = [
        migrations.RunPython(add_order_position, migrations.RunPython.noop)
    ]
