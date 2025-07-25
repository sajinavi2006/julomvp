# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2023-12-06 08:09
from __future__ import unicode_literals

from django.db import migrations

from juloserver.account_payment.models import CRMCustomerDetail


def populate_crm_customer_details(apps, schema_editor):
    data = [
        CRMCustomerDetail(
            section='Detail Pembayaran', attribute_name='Account ID',
            description="value will be int", sort_order=1,
            parameter_model_value={
                'execution_mode': 'only_execute',
                'models': {
                    'accountpayment': 'model.account.id',
                    'account': 'model.id',
                },
                'default_value': '-',
                'dom': '<strong> {} </strong>',
            }
        ),
        CRMCustomerDetail(
            section='Detail Pembayaran', attribute_name='Account Payment Status',
            description="Account payment status code and detail value will be str", sort_order=2,
            parameter_model_value={
                'execution_mode': 'only_execute',
                'models': {
                    'accountpayment': 'model.status',
                },
                'default_value': '-',
                'dom': '<strong> {} </strong>',
            }
        ),
        CRMCustomerDetail(
            section='Detail Pembayaran', attribute_name='Memenuhi Syarat Refinancing',
            description="Account payment status code and detail value will be str", sort_order=3,
            parameter_model_value={
                'execution_mode': 'execute_function',
                'models': {
                    'accountpayment': 'model.account',
                    'account': 'model',
                },
                'function_path': 'juloserver.loan_refinancing.services.offer_related',
                'function_name':'is_account_can_offered_refinancing',
                'function': 'function_name(model_identifier)',
                'default_value': '-',
                'dom': {
                    '-': '<strong> - </strong>',
                    True: '<strong> Ya </strong>',
                    False: '<strong> Tidak </strong>',
                },
            }
        ),
        CRMCustomerDetail(
            section='Detail Pembayaran', attribute_name='dpd',
            description="Due Paid Date oldest account payment value will be int", sort_order=4,
            parameter_model_value={
                'execution_mode': 'only_execute',
                'models': {
                    'accountpayment': 'model.dpd',
                },
                'default_value': '-',
                'dom': '<strong> {} </strong>',
            }
        ),
        CRMCustomerDetail(
            section='Detail Pembayaran', attribute_name='Customer Bucket Type',
            description="NA value will be string", sort_order=5,
            parameter_model_value={
                'execution_mode': 'execute_function',
                'models': {
                    'accountpayment': 'model',
                },
                'function_path': 'juloserver.minisquad.services',
                'function_name':'check_customer_bucket_type_account_payment',
                'function': 'function_name(model_identifier)',
                'default_value': 'NA',
                'dom': {
                    'NA': '<span class="label label-success">NA</span>',
                    'Fresh': '<span class="label label-success">Fresh</span>',
                    'Stabilized': '<span class="label label-red">Stabilized</span>',
                },
            }
        ),
        CRMCustomerDetail(
            section='Detail Pembayaran', attribute_name='Due Date',
            description="Due Date oldest account payment value will be ID date format", sort_order=6,
            parameter_model_value={
                'execution_mode': 'execute_function',
                'models': {
                    'accountpayment': 'model.due_date'
                },
                'function_path': 'babel.dates',
                'function_name':'format_date',
                'function': 'function_name(model_identifier, "d MMM yyyy", locale="id_ID")',
                'dom': '<strong> {} </strong>',
            }
        ),
        CRMCustomerDetail(
            section='Detail Pembayaran', attribute_name='Due Amount',
            description="Due Amount oldest account payment value will be money format", sort_order=7,
            parameter_model_value={
                'execution_mode': 'execute_function',
                'models': {
                    'accountpayment': 'model.due_amount'
                },
                'function_path': 'juloserver.julo.utils',
                'function_name':'display_rupiah',
                'function': 'function_name(model_identifier)',
                'dom': '<strong> {} </strong>',
            }
        ),
        CRMCustomerDetail(
            section='Detail Pembayaran', attribute_name='Late Fee Amount',
            description="Late Fee oldest account payment value will be money format", sort_order=8,
            parameter_model_value={
                'execution_mode': 'execute_function',
                'models': {
                    'accountpayment': 'model.late_fee_amount'
                },
                'function_path': 'juloserver.julo.utils',
                'function_name':'display_rupiah',
                'function': 'function_name(model_identifier)',
                'dom': '<strong> {} </strong>',
            }
        ),
        CRMCustomerDetail(
            section='Detail Pembayaran', attribute_name='Potensi Cashback',
            description="Potential cashback customer value will be money format", sort_order=9,
            parameter_model_value={
                'execution_mode': 'execute_function',
                'models': {
                    'accountpayment': 'model',
                },
                'function_path': 'juloserver.account_payment.services.account_payment_related',
                'function_name':'get_potential_cashback_for_crm',
                'function': 'function_name(model_identifier)',
                'dom': '<strong> {} </strong>',
            }
        ),
        CRMCustomerDetail(
            section='Detail Pembayaran', attribute_name='Cashback Diperoleh',
            description="Cashback already earned value will be money format", sort_order=10,
            parameter_model_value={
                'execution_mode': 'execute_function',
                'models': {
                    'accountpayment': 'model.total_cashback_earned()'
                },
                'function_path': 'juloserver.julo.utils',
                'function_name':'display_rupiah',
                'function': 'function_name(model_identifier)',
                'dom': '<strong> {} </strong>',
            }
        ),
        CRMCustomerDetail(
            section='Detail Pembayaran', attribute_name='Total Seluruh Perolehan Cashback',
            description="grand total cashback customer value will be money format", sort_order=11,
            parameter_model_value={
                'execution_mode': 'execute_function',
                'models': {
                    'accountpayment': 'model',
                },
                'function_path': 'juloserver.account_payment.services.account_payment_related',
                'function_name':'get_total_cashback_earned_for_crm',
                'function': 'function_name(model_identifier)',
                'dom': '<strong> {} </strong>',
            }

        ),
        CRMCustomerDetail(
            section='Detail Pembayaran', attribute_name='Paid Date',
            description="Paid Date value will be ID date format", sort_order=12,
            parameter_model_value={
                'execution_mode': 'execute_function',
                'models': {
                    'accountpayment': 'model.paid_date'
                },
                'function_path': 'babel.dates',
                'function_name':'format_date',
                'function': 'function_name(model_identifier, "d MMM yyyy", locale="id_ID")',
                'dom': '<strong> {} </strong>',
            }
        ),
        CRMCustomerDetail(
            section='Detail Pembayaran', attribute_name='Paid Amount',
            description="Paid Amount value will be money format", sort_order=13,
            parameter_model_value={
                'execution_mode': 'execute_function',
                'models': {
                    'accountpayment': 'model.paid_amount'
                },
                'function_path': 'juloserver.julo.utils',
                'function_name':'display_rupiah',
                'function': 'function_name(model_identifier)',
                'dom': '<strong> {} </strong>',
            }
        ),
        # Profil Pengguna
        CRMCustomerDetail(
            section='Profil Pengguna', attribute_name='Status Peneleponan',
            description="show customer should call or not", sort_order=1,
            parameter_model_value={
                'execution_mode': 'execute_function',
                'models': {
                    'accountpayment': 'model',
                },
                'function_path': 'juloserver.account_payment.services.account_payment_related',
                'function_name':'is_account_payment_blocked_for_call',
                'function': 'function_name(model_identifier)',
                'default_value': False,
                'dom': {
                    False: "<span class='label label-success'>Bisa</span>",
                    True: "<span class='label label-red'>Tidak Bisa</span>",
                }
            }
        ),
        CRMCustomerDetail(
            section='Profil Pengguna', attribute_name='Whatsapp Apps',
            description="boolean Yes or No", sort_order=2,
            parameter_model_value={
                'execution_mode': 'execute_function',
                'models': {
                    'accountpayment': 'model',
                },
                'function_path': 'juloserver.account_payment.services.account_payment_related',
                'function_name':'is_account_installed_apps',
                'function': 'function_name(model_identifier, apps_name=["WhatsApp", "Whatsapp"])',
                'default_value': '-',
                'dom': {
                    '-': '<strong> - </strong>',
                    True: '<strong> Yes </strong>',
                    False: '<strong> No </strong>',
                }
            }
        ),
        CRMCustomerDetail(
            section='Profil Pengguna', attribute_name='Telegram Apps',
            description="boolean Yes or No", sort_order=3,
            parameter_model_value={
                'execution_mode': 'execute_function',
                'models': {
                    'accountpayment': 'model',
                },
                'function_path': 'juloserver.account_payment.services.account_payment_related',
                'function_name':'is_account_installed_apps',
                'function': 'function_name(model_identifier, apps_name=["Telegram"])',
                'default_value': '-',
                'dom': {
                    '-': '<strong> - </strong>',
                    True: '<strong> Yes </strong>',
                    False: '<strong> No </strong>',
                }
            }
        ),
        CRMCustomerDetail(
            section='Profil Pengguna', attribute_name='Ever enter B5',
            description="for show if customer already entered B5 str", sort_order=4,
            parameter_model_value={
                'execution_mode': 'only_execute',
                'models': {
                    'accountpayment': 'model.account.ever_entered_B5',
                    'account': 'model.ever_entered_B5',
                },
                'default_value': '-',
                'dom': {
                    '-': '<strong> - </strong>',
                    True: '<strong> Yes </strong>',
                    False: '<strong> No </strong>',
                }
            }
        ),
        CRMCustomerDetail(
            section='Profil Pengguna',  attribute_name='FDC Risky Customer',
            description="FDC Risky Customer value will be boolean", sort_order=5,
            parameter_model_value={
                'execution_mode': 'query',
                'models': {
                    'accountpayment': 'model.account.last_application',
                    'account': 'model.last_application',
                },
                'orm_path':'juloserver.julo.models',
                'orm_object': 'FDCRiskyHistory',
                'query': 'orm_object.objects.filter(application_id=model_identifier.id).last()',
                'identifier': 'query.is_fdc_risky',
                'dom': {
                    '-': '<strong>-</strong>',
                    True: "<span class='label label-red'>Yes</span>",
                    False: "<span class='label label-success'>No</span>",
                }
            }
        ),
        CRMCustomerDetail(
            section='Profil Pengguna', attribute_name='Uninstall Indicator',
            description="Only have 2 value Install and uninstall value will be str", sort_order=6,
            parameter_model_value={
                'execution_mode': 'execute_function',
                'models': {
                    'accountpayment': 'model.account.customer_id',
                    'account': 'model.customer_id',
                    'application': 'model.customer_id',
                },
                'function_path': 'juloserver.minisquad.services2.dialer_related',
                'function_name':'get_uninstall_indicator_from_moengage_by_customer_id',
                'function': 'function_name(model_identifier)',
                'default_value': '-',
                'dom': '<strong> {} </strong>',
            }
        ),
        CRMCustomerDetail(
            section='Profil Pengguna', attribute_name='Autodebet', # checking
            description="Autodebet status value is boolean", sort_order=7,
            parameter_model_value={
                'execution_mode': 'execute_function',
                'models': {
                    'accountpayment': 'model.account',
                },
                'function_path': 'juloserver.autodebet.services.account_services',
                'function_name':'get_autodebet_bank_name',
                'function': 'function_name(model_identifier)',
                'default_value': '-',
                'dom_base_on_value': 'yes',
                'dom': {
                    '-': "<span class='label label-red'>Tidak Aktif</span>",
                    True: "<span class='label label-success'>Aktif</span><br><strong>{}</strong",
                },
            }
        ),
        CRMCustomerDetail(
            section='Profil Pengguna', attribute_name='Partner',
            description="partner name value will be str", sort_order=9,
            parameter_model_value={
                'execution_mode': 'only_execute',
                'models': {
                    'accountpayment': 'model.account.last_application.partner_name',
                    'account': 'model.last_application.partner_name',
                },
                'default_value': '-',
                'dom': '<strong> {} </strong>',
            }
        ),
        CRMCustomerDetail(
            section='Profil Pengguna', attribute_name='Tujuan peminjaman',
            description="Show tujuan peminjaman", sort_order=10,
            parameter_model_value={
                'execution_mode': 'only_execute',
                'models': {
                    'accountpayment': 'model.get_all_loan_purpose_for_crm',
                },
                'default_value': '-',
                'dom': '<strong> {} </strong>',
            }
        ),
        CRMCustomerDetail(
            section='Profil Pengguna', attribute_name='Transaksi pertama',
            description="Show Transaski pertama with date format", sort_order=11,
            parameter_model_value={
                'execution_mode': 'only_execute',
                'models': {
                    'accountpayment': 'model.account.get_first_loan_fund_transfer_ts_for_crm',
                },
                'default_value': '-',
                'dom': '<strong> {} </strong>',
            }
        ),
        CRMCustomerDetail(
            section='Profil Pengguna', attribute_name='Metode pembayaran terakhir',
            description="Show last used payment method", sort_order=12,
            parameter_model_value={
                'execution_mode': 'only_execute',
                'models': {
                    'accountpayment': 'model.account.get_last_used_payment_method_name',
                },
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
