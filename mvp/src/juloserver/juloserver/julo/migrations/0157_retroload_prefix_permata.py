# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2017-11-30 11:28
from __future__ import unicode_literals

from django.db import migrations, models
from django.conf import settings

def retroload_permata(apps, schema_editor):
    PaymentMethod = apps.get_model("julo", "PaymentMethod")
    payment_method = PaymentMethod.objects.all()
    for payment in payment_method:
        if payment.payment_method_code == '898532':
            payment.payment_method_code = settings.FASPAY_PREFIX_PERMATA
            va = payment.virtual_account[6:]
            payment.virtual_account =  settings.FASPAY_PREFIX_PERMATA + va
            payment.save()
                
                
class Migration(migrations.Migration):
    
    dependencies = [('julo', '0156_banklookup'),]

    operations = [
        migrations.RunPython(retroload_permata),
    ]