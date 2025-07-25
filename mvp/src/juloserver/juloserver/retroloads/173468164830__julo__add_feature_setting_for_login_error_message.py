# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2024-12-20 08:00
from __future__ import unicode_literals

from django.db import migrations
from juloserver.julo.models import FeatureSetting
from juloserver.julo.constants import FeatureNameConst


def run(apps, schema_editor):
    fs = FeatureSetting.objects
    if not fs.filter(feature_name=FeatureNameConst.LOGIN_ERROR_MESSAGE).exists():
        fs.create(
            feature_name=FeatureNameConst.LOGIN_ERROR_MESSAGE,
            category="Application",
            description="Feature setting for login error message",
            is_active=False,
            parameters={
                "existing_nik/email": {
                    "title": "NIK/Email Terdaftar atau Tidak Valid",
                    "message": "Silakan masuk atau ginakan NIK / email yang valid dan belum didaftarkan di JULO, ya.",
                    "button": "Mengerti",
                    "link_image": None,
                },
                "android_to_iphone": {
                    "title": " Kamu Tidak Bisa Masuk dengan HP Ini",
                    "message": "Silakan gunakan Androidmu untuk masuk ke JULO dan selesaikan dulu proses pendaftarannya. Jika sudah tak ada akses ke HP sebelumnya, silakan kontak CS kami, ya!",
                    "button": "Kembali",
                    "link_image": None,
                },
                "iphone_to_android": {
                    "title": " Kamu Tidak Bisa Masuk dengan HP Ini",
                    "message": "Silakan gunakan iPhonemu untuk masuk ke JULO dan selesaikan dulu proses pendaftarannya. Jika sudah tak ada akses ke HP sebelumnya, silakan kontak CS kami, ya!",
                    "button": "Kembali",
                    "link_image": None,
                },
            },
        )


class Migration(migrations.Migration):

    dependencies = []

    operations = [
        migrations.RunPython(run, migrations.RunPython.noop),
    ]
