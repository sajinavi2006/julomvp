# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import migrations, models


def seed_main_reasons(apps, schema_editor):
    LoanRefinancingMainReason = apps.get_model("loan_refinancing", "LoanRefinancingMainReason")
    main_reasons_data = [
        LoanRefinancingMainReason(
            reason='Perubahan Status Pekerjaan',
            is_active=True
        ),
        LoanRefinancingMainReason(
            reason='Masalah Keluarga / Perceraian',
            is_active=True
        ),
        LoanRefinancingMainReason(
            reason='Pengeluaran Tidak Terduga',
            is_active=True
        ),
        LoanRefinancingMainReason(
            reason='Sakit',
            is_active=True
        ),
        LoanRefinancingMainReason(
            reason='Pinjaman Lainnya',
            is_active=True
        ),
        LoanRefinancingMainReason(
            reason='Kehilangan Kerabat',
            is_active=True
        ),
        LoanRefinancingMainReason(
            reason='Bencana Alam',
            is_active=True
        ),
        LoanRefinancingMainReason(
            reason='Bangkrut',
            is_active=True
        ),
        LoanRefinancingMainReason(
            reason='Kesalahan Teknis Saat Melakukan Pembayaran',
            is_active=True
        ),
        LoanRefinancingMainReason(
            reason='Cicilan Terlalu Besar',
            is_active=True
        ),
        LoanRefinancingMainReason(
            reason='Keperluan Mendadak',
            is_active=True
        ),
        LoanRefinancingMainReason(
            reason='Tidak Mau Membayar',
            is_active=True
        ),
        LoanRefinancingMainReason(
            reason='Alasan Lainnya',
            is_active=True
        )]

    LoanRefinancingMainReason.objects.bulk_create(main_reasons_data)


class Migration(migrations.Migration):
    dependencies = [
        ('loan_refinancing', '0002_create_loan_refinancing_main_and_sub_reason_table'),
    ]

    operations = [
        migrations.RunPython(seed_main_reasons)
    ]
