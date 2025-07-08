# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import migrations, models


def seed_sub_reasons(apps, schema_editor):
    LoanRefinancingSubReason = apps.get_model("loan_refinancing", "LoanRefinancingSubReason")
    LoanRefinancingMainReason = apps.get_model("loan_refinancing", "LoanRefinancingMainReason")
    loan_refinancing_sub_reason_dict = {
        'Perubahan Status Pekerjaan': [
            'Penghasilan Lebih rendah ',
            'Kehilangan Pekerjaan',
            'Perubahan Tanggal Gajian'
        ],
        'Sakit': [
            'Peminjam Mengalami Sakit',
            'Kerabat Mengalami Sakit'
        ],
        'Kehilangan Kerabat': [
            'Kehilangan Suami/Istri',
            'Kehilangan Kerabat Lain'
        ],
        'Kesalahan Teknis Saat Melakukan Pembayaran': [
            'Pembayaran Gagal',
            'Tidak Bisa Membuka Aplikasi JULO',
            'Lupa Tanggal Jatuh Tempo Cicilan',
            'Tidak Tahu Tanggal Jatuh Tempo Cicilan'
        ]
    }

    main_reasons = LoanRefinancingMainReason.objects.all()

    for main_reason_obj in main_reasons:
        if main_reason_obj.reason in loan_refinancing_sub_reason_dict:
            sub_reason_list = []

            for sub_reason in loan_refinancing_sub_reason_dict[main_reason_obj.reason]:
                sub_reason_list.append(
                    LoanRefinancingSubReason(
                        reason=sub_reason,
                        is_active=True,
                        loan_refinancing_main_reason=main_reason_obj
                    )
                )

            LoanRefinancingSubReason.objects.bulk_create(sub_reason_list)


class Migration(migrations.Migration):
    dependencies = [
        ('loan_refinancing', '0003_seed_main_reason_table'),
    ]

    operations = [
        migrations.RunPython(seed_sub_reasons)
    ]
