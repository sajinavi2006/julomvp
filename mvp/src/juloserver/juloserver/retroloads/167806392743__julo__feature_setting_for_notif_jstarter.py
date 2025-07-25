# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2023-03-06 00:52
from __future__ import unicode_literals

from django.db import migrations
from juloserver.julo.models import FeatureSetting
from juloserver.julo.constants import FeatureNameConst


def execute(apps, schema_editor):

    feature_name = FeatureNameConst.SECOND_CHECK_JSTARTER_MESSAGE
    if not FeatureSetting.objects.filter(feature_name=feature_name).exists():
        FeatureSetting.objects.create(
            feature_name=feature_name,
            is_active=True,
            parameters={
                "dukcapil_true_heimdall_true": {
                    "title": "Selamat Akun Kamu Sudah Aktif!",
                    "body": "Limitmu sudah tersedia dan bisa langsung kamu gunakan untuk transaksi, lho!",
                    "destination": "julo_starter_second_check_ok"
                },
                "dukcapil_false": {
                    "title": "Pembuatan Akun JULO Starter Gagal",
                    "body": "Kamu belum memenuhi kriteria JULO Starter",
                    "destination": "julo_starter_second_check_rejected"
                },
                "dukcapil_true_heimdall_false": {
                    "title": "Pembuatan Akun JULO Starter Gagal",
                    "body": "Kamu belum memenuhi kriteria. Tapi kamu masih bisa ajukan pembuatan akun JULO Kredit Digital, kok!",
                    "destination": "julo_starter_eligbility_j1_offer"
                }
            },
            category='application',
            description='To manage message notification in JStarter',
        )


class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.RunPython(execute, migrations.RunPython.noop),
    ]
