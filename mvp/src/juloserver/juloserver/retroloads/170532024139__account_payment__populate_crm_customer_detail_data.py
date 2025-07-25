# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2024-01-15 12:04
from __future__ import unicode_literals

from django.db import migrations

from juloserver.account_payment.models import CRMCustomerDetail


def populate_crm_customer_details(apps, schema_editor):
    data = [
        CRMCustomerDetail(
            section='Profil Pengguna', attribute_name='Skema Cashback Baru',
            description="check is customer cashback new scheme or not", sort_order=13,
            parameter_model_value={
                'execution_mode': 'execute_function',
                'models': {
                    'accountpayment': 'model.account.id',
                    'account': 'model.id',
                },
                'function_path': 'juloserver.account_payment.services.earning_cashback',
                'function_name': 'get_cashback_experiment',
                'function': 'function_name(model_identifier)',
                'default_value': False,
                'dom': {
                    True: '<strong> Yes </strong>',
                    False: '<strong> No </strong>',
                }
            }
        ),
        CRMCustomerDetail(
            section='Detail Pembayaran', attribute_name='Presentase Potensi Cashback',
            description="percentage potential cashback account", sort_order=10,
            parameter_model_value={
                'execution_mode': 'execute_function',
                'models': {
                    'accountpayment': 'model',
                },
                'function_path': 'juloserver.account_payment.services.account_payment_related',
                'function_name': 'get_percentage_potential_cashback_for_crm',
                'function': 'function_name(model_identifier)',
                'default_value': '-',
                'dom': '<strong> {} </strong>',
            }
        ),
    ]
    CRMCustomerDetail.objects.bulk_create(data)

class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.RunPython(populate_crm_customer_details, migrations.RunPython.noop),
    ]
