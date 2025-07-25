# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2018-03-28 05:02
from __future__ import unicode_literals

from django.db import migrations, models

def add_payments_method_lookup_alfamart(apps, schema_editor):
    PaymentMethodLookup = apps.get_model("julo", "PaymentMethodLookup")
    method_lookups = PaymentMethodLookup.objects.filter(name='ALFAMART').first()
    if not method_lookups:
        PaymentMethodLookup.objects.create(code='319322',name='ALFAMART')

def add_payments_method_lookup_indomaret(apps, schema_editor):
    PaymentMethodLookup = apps.get_model("julo", "PaymentMethodLookup")
    method_lookups = PaymentMethodLookup.objects.filter(name='INDOMARET').first()
    if not method_lookups:
        PaymentMethodLookup.objects.create(code='319237',name='INDOMARET')

def update_payment_methods(apps, schema_editor):
    PaymentMethodLookup = apps.get_model("julo", "PaymentMethodLookup")
    method_lookups = PaymentMethodLookup.objects.all()
    base_url = 'https://www.julo.co.id/images/payment_methods/'
    for method in method_lookups:
        if method.name == 'Bank BCA':
            method.bank_virtual_name = 'BCA Virtual Account'
            method.image_logo_url = base_url + 'bank_bca/bca.png'
            method.image_background_url = base_url + 'bank_bca/background_bca.png'
        elif method.name == 'Bank CIMB Niaga':
            method.bank_virtual_name = 'CIMB Virtual Account'
            method.image_logo_url = base_url + 'bank_cimb/cimb.png'
            method.image_background_url = base_url + 'bank_cimb/background_cimb.png'
        elif method.name == 'Bank MANDIRI':
            method.bank_virtual_name = 'Mandiri Virtual Account'
            method.image_logo_url = base_url + 'bank_mandiri/mandiri.png'
            method.image_background_url = base_url + 'bank_mandiri/background_mandiri.png'
        elif method.name == 'Bank BRI':
            method.bank_virtual_name = 'BRI Virtual Account'
            method.image_logo_url = base_url + 'bank_bri/bri.png'
            method.image_background_url = base_url + 'bank_bri/background_bri.png'
        elif method.name == 'Bank Tabungan Negara':
            method.bank_virtual_name = 'BTN Virtual Account'
            method.image_logo_url = base_url + 'bank_btn/btn.png'
            method.image_background_url = base_url + 'bank_btn/background_btn.png'
        elif method.name == 'Bank MEGA':
            method.bank_virtual_name = 'Mega Virtual Account'
            method.image_logo_url = base_url + 'bank_mega/mega.png'
            method.image_background_url = base_url + 'bank_mega/background_mega.png'
        elif method.name == 'Bank SYARIAH MANDIRI':
            method.bank_virtual_name = 'Mandiri Syariah Virtual Account'
            method.image_logo_url = base_url + 'bank_mandiri_syariah/mandiri_syariah.png'
            method.image_background_url = base_url + 'bank_mandiri_syariah/background_mandiri_syariah.png'
        elif method.name == 'Bank SINARMAS':
            method.bank_virtual_name = 'Sinarmas Virtual Account'
            method.image_logo_url = base_url + 'bank_sinarmas/sinarmas.png'
            method.image_background_url = base_url + 'bank_sinarmas/background_sinarmas.png'
        elif method.name == 'Bank PERMATA':
            method.bank_virtual_name = 'Permata Virtual Account'
            method.image_logo_url = base_url + 'bank_permata/permata.png'
            method.image_background_url = base_url + 'bank_permata/background_permata.png'
        elif method.name == 'INDOMARET':
            method.bank_virtual_name = 'Indomaret'
            method.image_logo_url = base_url + 'indomaret/indomaret.png'
            method.image_background_url = base_url + 'indomaret/background_indomaret.png'
        elif method.name == 'ALFAMART':
            method.bank_virtual_name = 'Alfamart'
            method.image_logo_url = base_url + 'alfamart/alfamart.png'
            method.image_background_url = base_url + 'alfamart/background_alfamart.png'
        elif method.name == 'Doku':
            method.bank_virtual_name = 'Doku Account'
            method.image_logo_url = base_url + 'doku/doku.png'
            method.image_background_url = base_url + 'doku/background_doku.png'
        elif method.name == 'Bank BNI':
            method.bank_virtual_name = 'BNI Virtual Account'
            method.image_logo_url = base_url + 'bank_bni/bni.png'
            method.image_background_url = base_url + 'bank_bni/background_bni.png'
        method.save()

class Migration(migrations.Migration):

    dependencies = [
        ('julo', '0205_auto_20180329_1110'),
    ]

    operations = [
        migrations.AddField(
            model_name='paymentmethodlookup',
            name='bank_virtual_name',
            field=models.CharField(blank=True, max_length=50, null=True),
        ),
        migrations.AddField(
            model_name='paymentmethodlookup',
            name='image_background_url',
            field=models.CharField(blank=True, max_length=500, null=True),
        ),
        migrations.AddField(
            model_name='paymentmethodlookup',
            name='image_logo_url',
            field=models.CharField(blank=True, max_length=500, null=True),
        ),
        migrations.RunPython(add_payments_method_lookup_alfamart, migrations.RunPython.noop),
        migrations.RunPython(add_payments_method_lookup_indomaret, migrations.RunPython.noop),
        migrations.RunPython(update_payment_methods, migrations.RunPython.noop),
    ]
