# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2018-03-28 05:02
from __future__ import unicode_literals

from django.db import migrations, models

def add_payments_method_lookup_maybank(apps, schema_editor):
    PaymentMethodLookup = apps.get_model("julo", "PaymentMethodLookup")
    method_lookups = PaymentMethodLookup.objects.filter(name='Bank MAYBANK').first()
    base_url = 'https://www.julo.co.id/images/payment_methods/'
    if not method_lookups:
        PaymentMethodLookup.objects.create(
            code='782182',
            name='Bank MAYBANK',
            bank_virtual_name='Maybank Virtual Account',
            image_logo_url='maybank/maybank.png',
            image_background_url='maybank/background_maybank.png')

class Migration(migrations.Migration):

    dependencies = [
        ('julo', '0206_auto_20180329_1736'),
    ]

    operations = [
        migrations.RunPython(add_payments_method_lookup_maybank, migrations.RunPython.noop),
    ]
