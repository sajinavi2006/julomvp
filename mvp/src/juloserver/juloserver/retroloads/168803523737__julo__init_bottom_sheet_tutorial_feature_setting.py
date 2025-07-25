# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2023-06-29 10:40
from __future__ import unicode_literals

from django.db import migrations
from juloserver.julo.models import FeatureSetting


def add_feature_setting(apps, _schema_editor):
    FeatureSetting.objects.create(
        feature_name="tutorial_bottom_sheet",
        is_active=True,
        parameters={
            'title': 'Aktifkan Lokasi di Google Chrome, Ya!',
            'image_url': 'info-card/TUTORIAL_BOTTOM_SHEET.png',
            'subtitle': 'Biar bisa lanjut proses registrasinya, aktifkan lokasimu dulu, '
                        'yuk!!!! Gini caranya:',
            'step': (
                '<ul>'
                    '<li>Buka “Setting” di Google Chrome</li>'
                    '<li>Klik “Site settings” lalu klik “Location”</li>'
                    '<li>Lihat bagian “Blocked” lalu klik “julo.co.id”</li>'
                    '<li>Ubah dari “Block” ke “Allow”</li>'
                    '<li>Asik, aktivasi lokasimu di Google Chrome berhasil!</li>'
                '</ul>'
            ),
            'button_text': 'Mengerti',
        }
    )


class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.RunPython(add_feature_setting, migrations.RunPython.noop),
    ]
