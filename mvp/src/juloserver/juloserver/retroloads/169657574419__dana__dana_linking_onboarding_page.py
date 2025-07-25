# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2023-10-06 07:02
from __future__ import unicode_literals

from django.conf import settings
from django.db import migrations

from juloserver.julo.constants import FeatureNameConst
from juloserver.julo.models import FeatureSetting


def create_feature_settings_dana_onboarding_page(apps, _schema_editor):
    base_url = settings.STATIC_URL + 'images/new_payment_methods/'

    FeatureSetting.objects.create(
        feature_name=FeatureNameConst.DANA_LINKING_ONBOARDING,
        parameters=[
            {
                'benefit_title': 'Bayar Anti Ribet',
                'benefit_content': 'Tak perlu keluar rumah, pembayaran cukup dari HP kamu saja!',
                'benefit_icon': base_url + 'dana/benefit_content/bayar_anti_ribet.png',
            },
            {
                'benefit_title': 'Proses Cepat',
                'benefit_content': 'Pembayaran dapat selesai hanya dalam 2 langkah!',
                'benefit_icon': base_url + 'dana/benefit_content/proses_cepat.png',
            },
            {
                'benefit_title': 'Saldo DANA Langsung Terlihat',
                'benefit_content': 'Tak perlu buka aplikasi DANA untuk lihat saldo DANA-mu!',
                'benefit_icon': base_url + 'dana/benefit_content/dana_viewable_balance.png',
            }
        ],
        is_active=True,
        category='repayment',
        description='DANA onboarding page'
    )


class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.RunPython(create_feature_settings_dana_onboarding_page,
                             migrations.RunPython.noop),
    ]
