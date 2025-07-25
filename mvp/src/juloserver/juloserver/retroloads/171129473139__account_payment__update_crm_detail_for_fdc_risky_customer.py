# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2024-03-24 15:38
from __future__ import unicode_literals

from django.db import migrations
from juloserver.account_payment.models import CRMCustomerDetail


def update_fdc_crm_detail(apps, _schema_editor):
    existing_crm_detail = CRMCustomerDetail.objects.filter(
        attribute_name='FDC Risky Customer')
    parameter_data = {
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
            True: "<span class='label label-red'>Yes</span>&nbsp;<span> {} </span>",
            False: "<span class='label label-success'>No</span>&nbsp;<span> {} </span>",
        }
    }
    if existing_crm_detail.exists():
        existing_crm_detail.update(parameter_model_value=parameter_data)


class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.RunPython(update_fdc_crm_detail, migrations.RunPython.noop),
    ]
