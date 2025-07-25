# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2022-06-08 07:32
from __future__ import unicode_literals

from django.db import migrations

from juloserver.julo.models import FeatureSetting
from juloserver.credit_card.constants import FeatureNameConst


def add_feature_setting_credit_card_faq(apps, schema_editor):
    faq_parameter = [
        {
            'title': 'Cara Aktivasi',
            'items': [
                'Daftar dan masukkan alamatmu', 'Cukup verifikasi dengan selfie',
                'Tunggu kartu kamu dikirim ke alamatmu', 'Kamu langsung bisa gunakan JULO Card'
            ]
        },
        {
            'title': 'Cara Transaksi',
            'items': [
                'Pilih tenor untuk pembayaran',
                'Cek dan lanjutkan proses Surat Perjanjian Utang Piutang',
                'Kamu bisa lakukan transaksi di mana saja pada merchant yang dapat '
                'menerima logo "GPN"', 'Kartu Kredit bisa untuk pembayaran fisik pada '
                'mesin EDC ataupun transaksi online.',
            ]
        },
        {
            'title': 'Cara Ganti Tenor',
            'items': [
                'Pilihan ubah tenor akan muncul ketika kamu telah selesai bertransaksi.',
                'Sesuaikan dengan rencana kamu, dan pilih tenor yang tepat.',
                'Atau, kamu juga bisa set tenor secara default sesuai pilihan JULO.',
                'Pergantian tenor hanya bisa saat selesai transaksi, ya. Jadi, '
                'jangan lupa untuk tentukan pilihanmu secepatnya.'
            ]
        },
        {
            'title': 'Cara Blokir dan Membuka Blokir',
            'items': [
                'Kamu bisa memblokir JULO Card langsung dari aplikasi dengan '
                'memilih alasan kenapa kamu harus memblokir kartu kamu.',
                'Jika kamu kehilangan kartu, agar aman, '
                'kamu bisa menghubungi customer service JULO.',
                'Untuk membuka blokir, kamu cukup menghubungi customer service kembali.'
            ]
        },
    ]

    FeatureSetting.objects.create(
        feature_name=FeatureNameConst.CREDIT_CARD_FAQ,
        parameters=faq_parameter,
        is_active=True,
        description='FAQ for credit card',
        category='credit card'
    )


class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.RunPython(add_feature_setting_credit_card_faq, migrations.RunPython.noop),
    ]
