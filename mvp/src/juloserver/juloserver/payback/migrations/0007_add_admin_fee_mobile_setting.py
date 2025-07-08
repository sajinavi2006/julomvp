# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import migrations


def add_gopay_admin_fee_mobile_setting(apps, schema_editor):
    MobileFeatureSetting = apps.get_model("julo", "MobileFeatureSetting")

    gopay_admin_fee_obj = MobileFeatureSetting.objects.filter(feature_name='gopay_admin_fee').first()
    if not gopay_admin_fee_obj:
        gopay_admin_fee_obj = MobileFeatureSetting(feature_name="gopay_admin_fee")
    gopay_admin_fee_obj.is_active = False
    gopay_admin_fee_obj.parameters = {"admin_percent_fee": 2}
    gopay_admin_fee_obj.save()


class Migration(migrations.Migration):

    dependencies = [
        ('payback', '0006_retro_gopay_payment_method'),
    ]

    operations = [
        migrations.RunPython(add_gopay_admin_fee_mobile_setting),
    ]
