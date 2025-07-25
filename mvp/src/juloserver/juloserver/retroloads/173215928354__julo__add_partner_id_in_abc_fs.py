# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2024-11-21 03:21
from __future__ import unicode_literals

from django.db import migrations
from juloserver.julo.models import FeatureSetting
from juloserver.antifraud.constant.feature_setting import BinaryCheck


def update_abc_feature_settings_to_apply_bypass_holdout_by_partner_id(apps, _schema_editor):
    abc_fs_list = [
        "abc_gd_device_sharing_block",
        "abc_suspicious_apps",
        "abc_blacklisted_postal_code",
        "abc_bank_name_velocity_jturbo",
        "abc_telco_maid_location",
        "abc_email_domain",
        "abc_kredibel",
        "abc_close_kin_contact_jturbo",
        "abc_fraudster_name",
        "abc_bank_name_velocity",
        "abc_fraudulent_bank_account_and_phone_number",
        "abc_fraudulent_bank_account_and_phone_number_jturbo",
        "abc_swift_limit_drainer",
        "abc_swift_limit_drainer_jturbo",
        "abc_telco_maid_location_jturbo",
        "abc_close_kin_contact",
        "abc_blacklisted_geohash5",
        "abc_play_integrity_emulator",
        "abc_blacklisted_asn",
        "abc_blacklisted_company",
    ]

    for abc_fs in abc_fs_list:
        feature_setting: FeatureSetting = FeatureSetting.objects.filter(feature_name=abc_fs).last()
        if not feature_setting:
            return
        if BinaryCheck.Parameter.HOLDOUT in feature_setting.parameters:
            feature_setting.parameters[BinaryCheck.Parameter.HOLDOUT][
                BinaryCheck.Parameter.Holdout.PARTNER_IDS
            ] = []
            feature_setting.save()
    return


class Migration(migrations.Migration):

    dependencies = []

    operations = [
        migrations.RunPython(
            update_abc_feature_settings_to_apply_bypass_holdout_by_partner_id,
            migrations.RunPython.noop,
        )
    ]
