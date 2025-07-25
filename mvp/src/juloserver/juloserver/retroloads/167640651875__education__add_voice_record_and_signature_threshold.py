# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2023-02-14 20:28
from __future__ import unicode_literals

from django.db import migrations
from juloserver.application_flow.models import (
    DigitalSignatureThreshold,
    VoiceRecordingThreshold,
)
from juloserver.julo.models import (
    FeatureSetting,
    MobileFeatureSetting,
)


def add_education_voice_record_and_signature_threshold(apps, schema_editor):
    METHOD_ID = 13
    VoiceRecordingThreshold.objects.create(
        transaction_method_id=METHOD_ID,
        parameters={'voice_recording_loan_amount_threshold': '1000000'}
    )
    DigitalSignatureThreshold.objects.create(
        transaction_method_id=METHOD_ID,
        parameters={'digital_signature_loan_amount_threshold': '50000'}
    )


def update_feature_otp_transaction_flow(apps, schema_editor):
    feature_setting, _ = FeatureSetting.objects.get_or_create(feature_name='otp_action_type')
    parameters = feature_setting.parameters or {}
    if 'transaction_education' not in parameters:
        parameters.update({
            "transaction_education": "long_lived",
        })
    feature_setting.parameters = parameters
    feature_setting.save()


def update_feature_setting_for_transaction_otp_pdam(apps, schema_editor):
    feature_setting, created = MobileFeatureSetting.objects.get_or_create(feature_name='otp_setting')
    parameters = feature_setting.parameters or {}
    transaction_settings = parameters['transaction_settings'] or {}
    transaction_settings['transaction_education'] = {
        "is_active": True,
        "minimum_transaction": 0
    }
    parameters.update({
        "transaction_document": "",
        "transaction_settings": transaction_settings
    })
    feature_setting.parameters = parameters
    feature_setting.save()


class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.RunPython(add_education_voice_record_and_signature_threshold),
        migrations.RunPython(update_feature_otp_transaction_flow),
        migrations.RunPython(update_feature_setting_for_transaction_otp_pdam),
    ]
