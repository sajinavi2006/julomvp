# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2024-05-13 09:58
from __future__ import unicode_literals

from django.db import migrations

from juloserver.julo.models import FeatureSetting
from juloserver.loan.constants import LoanFeatureNameConst
from juloserver.payment_point.constants import TransactionMethodCode


def add_fs_transaction_result(apps, schema_editor):
    params = {
        'minimum_app_version': '8.25.0',
        'allowed_methods': [
            TransactionMethodCode.SELF.code,
            TransactionMethodCode.OTHER.code,
            TransactionMethodCode.PULSA_N_PAKET_DATA.code,
            TransactionMethodCode.PASCA_BAYAR.code,
            TransactionMethodCode.DOMPET_DIGITAL.code,
            TransactionMethodCode.LISTRIK_PLN.code,
            TransactionMethodCode.BPJS_KESEHATAN.code,
            TransactionMethodCode.E_COMMERCE.code,
            TransactionMethodCode.TRAIN_TICKET.code,
            TransactionMethodCode.PDAM.code,
            TransactionMethodCode.EDUCATION.code,
            TransactionMethodCode.HEALTHCARE.code,
        ],
    }

    FeatureSetting.objects.update_or_create(
        feature_name=LoanFeatureNameConst.TRANSACTION_RESULT_NOTIFICATION,
        defaults={
            'is_active': True,
            'category': 'loan',
            'description': 'Configurations for sending transaction result for Push Notif',
            'parameters': params,
        },
    )


class Migration(migrations.Migration):

    dependencies = []

    operations = [
        migrations.RunPython(
            code=add_fs_transaction_result,
            reverse_code=migrations.RunPython.noop,
        ),
    ]
