# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2021-08-16 09:34
from __future__ import unicode_literals

from django.db import migrations
from juloserver.julo.models import FrontendView


def update_frontend_view(apps, schema_editor):
    data_to_be_updated = [
        {
            'label_name': 'TKB90',
            'label_code': 'tkb_90'
        },
        {
            'label_name': 'Total pinjaman sejak didirikan',
            'label_code': 'total_pinjaman_sejak_didirikan'
        },
        {
            'label_name': 'Total pinjaman tahun ini',
            'label_code': 'total_pinjaman_tahun_ini'
        },
        {
            'label_name': 'Total pinjaman outstanding',
            'label_code': 'total_pinjaman_outstanding'
        },
        {
            'label_name': 'Total peminjam',
            'label_code': 'total_peminjam'
        },
        {
            'label_name': 'Total peminjam aktif',
            'label_code': 'total_peminjam_aktif'
        },
    ]

    for data in data_to_be_updated:
        frontend = FrontendView.objects.filter(label_name=data['label_name']).last()
        frontend.label_code = data['label_code']
        frontend.save()


class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.RunPython(update_frontend_view, migrations.RunPython.noop)
    ]
