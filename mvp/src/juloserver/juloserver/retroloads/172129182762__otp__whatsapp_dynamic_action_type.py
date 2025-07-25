# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2024-07-18 08:37
from __future__ import unicode_literals

from django.db import migrations
from juloserver.julo.constants import MobileFeatureNameConst
from juloserver.julo.models import MobileFeatureSetting


def add_new_feature_setting(apps, _schema_editor):
    created_data = {
        'feature_name': MobileFeatureNameConst.WHATSAPP_DYNAMIC_ACTION_TYPE,
        'is_active': False,
        'parameters': {
            'active_allowed_action_type': [
                'LOGIN',
                'VERIFY_PHONE_NUMBER',
                'PRE_LOGIN_RESET_PIN',
                'TRANSACTION_SELF',
                'TRANSACTION_DOMPET_DIGITAL',
                'ADD_BANK_ACCOUNT_DESTINATION',
                'ACCOUNT_DELETION_REQUEST',
                'TRANSACTION_PULSA_DAN_DATA',
                'VERIFY_PHONE_NUMBER_2',
                'PHONE_REGISTER',
                'REGISTER',
                'CHANGE_PHONE_NUMBER',
                'TRANSACTION_LISTRIK_PLN',
                'TRANSACTION_ECOMMERCE',
                'PRE_LOGIN_CHANGE_PHONE',
                'TRANSACTION_OTHER',
                'TRANSACTION_EDUCATION',
                'TRANSACTION_PASCA_BAYAR',
                'TRANSACTION_PDAM',
                'TRANSACTION_BPJS_KESEHATAN',
                'TRANSACTION_TRAIN_TICKET',
                'TRANSACTION_HEALTHCARE',
            ],
            'inactive_allowed_action_type': [],
        },
    }
    MobileFeatureSetting.objects.create(**created_data)


class Migration(migrations.Migration):

    dependencies = []

    operations = [
        migrations.RunPython(add_new_feature_setting, migrations.RunPython.noop),
    ]
