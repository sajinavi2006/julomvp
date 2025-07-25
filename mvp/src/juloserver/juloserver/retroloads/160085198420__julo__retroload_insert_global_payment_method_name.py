# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2020-09-23 09:06
from __future__ import unicode_literals

from django.db import migrations
from juloserver.julo.models import GlobalPaymentMethod


def db_insert_payment_method_name(apps, schema_editor):
    payment_method_views = [
        {
            'feature_name': 'BCA',
            'payment_method_name': 'Bank BCA',
        },
        {
            'feature_name': 'Permata',
            'payment_method_name': 'PERMATA Bank',
        },
        {
            'feature_name': 'BRI',
            'payment_method_name': 'Bank BRI',
        },
        {
            'feature_name': 'Maybank',
            'payment_method_name': 'Bank MAYBANK',
        },
        {
            'feature_name': 'Gopay',
            'payment_method_name': 'Gopay',
        },
        {
            'feature_name': 'Alfamart',
            'payment_method_name': 'ALFAMART'
        },
        {
            'feature_name': 'Indomaret',
            'payment_method_name': 'INDOMARET'
        },
    ]
    for payment_method_view in payment_method_views:
        payment_method = GlobalPaymentMethod.objects.get(
            feature_name=payment_method_view['feature_name'])
        payment_method.update_safely(payment_method_name=payment_method_view['payment_method_name'])


class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.RunPython(db_insert_payment_method_name, migrations.RunPython.noop)
    ]
