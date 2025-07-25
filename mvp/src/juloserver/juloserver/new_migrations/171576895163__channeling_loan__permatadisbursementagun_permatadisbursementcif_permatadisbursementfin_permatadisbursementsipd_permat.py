# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2024-05-15 10:29
from __future__ import unicode_literals

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = []

    operations = [
        migrations.CreateModel(
            name='PermataDisbursementAgun',
            fields=[
                ('cdate', models.DateTimeField(auto_now_add=True)),
                ('udate', models.DateTimeField(auto_now=True)),
                (
                    'id',
                    models.AutoField(
                        db_column='permata_channeling_disbursement_agun_id',
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                ('no_pin', models.CharField(blank=True, max_length=200, null=True)),
                ('merk', models.CharField(blank=True, max_length=200, null=True)),
                ('jenis', models.CharField(blank=True, max_length=200, null=True)),
                ('model', models.CharField(blank=True, max_length=200, null=True)),
                ('nopol', models.CharField(blank=True, max_length=200, null=True)),
                ('norang', models.CharField(blank=True, max_length=200, null=True)),
                ('nomes', models.CharField(blank=True, max_length=200, null=True)),
                ('warna', models.CharField(blank=True, max_length=200, null=True)),
                ('tahun_mobil', models.CharField(blank=True, max_length=200, null=True)),
                ('tahun_rakit', models.CharField(blank=True, max_length=200, null=True)),
                ('clinder', models.CharField(blank=True, max_length=200, null=True)),
                ('kelompok', models.CharField(blank=True, max_length=200, null=True)),
                ('penggunaan', models.CharField(blank=True, max_length=200, null=True)),
                ('nilai_score', models.CharField(blank=True, max_length=200, null=True)),
                ('tempat_simpan', models.CharField(blank=True, max_length=200, null=True)),
            ],
            options={
                'db_table': '"ana"."permata_channeling_disbursement_agun"',
                'managed': False,
            },
        ),
        migrations.CreateModel(
            name='PermataDisbursementCif',
            fields=[
                ('cdate', models.DateTimeField(auto_now_add=True)),
                ('udate', models.DateTimeField(auto_now=True)),
                (
                    'id',
                    models.AutoField(
                        db_column='permata_channeling_disbursement_cif_id',
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                ('loan_id', models.CharField(blank=True, max_length=200, null=True)),
                ('application_id', models.CharField(blank=True, max_length=200, null=True)),
                ('nama', models.CharField(blank=True, max_length=200, null=True)),
                ('nama_rekanan', models.CharField(blank=True, max_length=200, null=True)),
                ('nama_cabang', models.CharField(blank=True, max_length=200, null=True)),
                ('alamat_cbg1', models.CharField(blank=True, max_length=200, null=True)),
                ('alamat_cbg2', models.CharField(blank=True, max_length=200, null=True)),
                ('kota', models.CharField(blank=True, max_length=200, null=True)),
                ('usaha', models.CharField(blank=True, max_length=200, null=True)),
                ('alamat_deb1', models.CharField(blank=True, max_length=200, null=True)),
                ('kota_deb', models.CharField(blank=True, max_length=200, null=True)),
                ('npwp', models.CharField(blank=True, max_length=200, null=True)),
                ('ktp', models.CharField(blank=True, max_length=200, null=True)),
                ('tgl_lahir', models.DateField(blank=True, null=True)),
                ('tgl_novasi', models.CharField(blank=True, max_length=200, null=True)),
                ('tmpt_lahir', models.CharField(blank=True, max_length=200, null=True)),
                ('coderk', models.CharField(blank=True, max_length=200, null=True)),
                ('no_rekening', models.CharField(blank=True, max_length=200, null=True)),
                ('tgl_proses', models.DateField(blank=True, null=True)),
                ('kelurahan', models.CharField(blank=True, max_length=200, null=True)),
                ('kecamatan', models.CharField(blank=True, max_length=200, null=True)),
                ('kode_pos', models.CharField(blank=True, max_length=200, null=True)),
                ('status_acc', models.CharField(blank=True, max_length=200, null=True)),
                ('nama_ibu', models.CharField(blank=True, max_length=200, null=True)),
                ('pekerjaan', models.CharField(blank=True, max_length=200, null=True)),
                ('usaha_dimana_bkrj', models.CharField(blank=True, max_length=200, null=True)),
                ('nama_alias', models.CharField(blank=True, max_length=200, null=True)),
                ('status', models.CharField(blank=True, max_length=200, null=True)),
                ('ket_status', models.CharField(blank=True, max_length=200, null=True)),
                ('customer_grouping', models.CharField(blank=True, max_length=200, null=True)),
                ('pasport', models.CharField(blank=True, max_length=200, null=True)),
                ('kodearea', models.CharField(blank=True, max_length=200, null=True)),
                ('telepon', models.CharField(blank=True, max_length=200, null=True)),
                ('jenis_kelamin', models.CharField(blank=True, max_length=200, null=True)),
                ('sandi_pkrj', models.CharField(blank=True, max_length=200, null=True)),
                ('tempat_bekerja', models.CharField(blank=True, max_length=200, null=True)),
                ('bidang_usaha', models.CharField(blank=True, max_length=200, null=True)),
                ('akte_awal', models.CharField(blank=True, max_length=200, null=True)),
                ('tgl_akte_awal', models.CharField(blank=True, max_length=200, null=True)),
                ('akte_akhir', models.CharField(blank=True, max_length=200, null=True)),
                ('tgl_akte_akhir', models.CharField(blank=True, max_length=200, null=True)),
                ('tgl_berdiri', models.CharField(blank=True, max_length=200, null=True)),
                ('dati_debitur', models.CharField(blank=True, max_length=200, null=True)),
                ('hp', models.CharField(blank=True, max_length=200, null=True)),
                ('dati_lahir', models.CharField(blank=True, max_length=200, null=True)),
                ('tmpt_lhr_dati', models.CharField(blank=True, max_length=200, null=True)),
                ('nama_lengkap', models.CharField(blank=True, max_length=200, null=True)),
                ('alamat', models.CharField(blank=True, max_length=200, null=True)),
                ('tlp_rumah', models.CharField(blank=True, max_length=200, null=True)),
                (
                    'kode_jenis_penggunaan_lbu',
                    models.CharField(blank=True, max_length=200, null=True),
                ),
                (
                    'kode_jenis_penggunaan_sid',
                    models.CharField(blank=True, max_length=200, null=True),
                ),
                (
                    'kode_golongan_kredit_umkm_lbu_sid',
                    models.CharField(blank=True, max_length=200, null=True),
                ),
                (
                    'kode_kategori_portfolio_lbu',
                    models.CharField(blank=True, max_length=200, null=True),
                ),
                ('credit_scoring', models.CharField(blank=True, max_length=200, null=True)),
            ],
            options={
                'db_table': '"ana"."permata_channeling_disbursement_cif"',
                'managed': False,
            },
        ),
        migrations.CreateModel(
            name='PermataDisbursementFin',
            fields=[
                ('cdate', models.DateTimeField(auto_now_add=True)),
                ('udate', models.DateTimeField(auto_now=True)),
                (
                    'id',
                    models.AutoField(
                        db_column='permata_channeling_disbursement_fin_id',
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                ('no_pin', models.CharField(blank=True, max_length=200, null=True)),
                ('tgl_pk', models.DateField(blank=True, null=True)),
                ('tgl_valid', models.DateField(blank=True, null=True)),
                ('tgl_angs1', models.DateField(blank=True, null=True)),
                ('jmlh_angs', models.CharField(blank=True, max_length=200, null=True)),
                ('cost', models.CharField(blank=True, max_length=200, null=True)),
                ('cost_bank', models.CharField(blank=True, max_length=200, null=True)),
                ('addm', models.CharField(blank=True, max_length=200, null=True)),
                ('ang_deb', models.CharField(blank=True, max_length=200, null=True)),
                ('angs_bank', models.CharField(blank=True, max_length=200, null=True)),
                ('bunga', models.CharField(blank=True, max_length=200, null=True)),
                ('bunga_bank', models.CharField(blank=True, max_length=200, null=True)),
                ('kondisi_agun', models.CharField(blank=True, max_length=200, null=True)),
                ('nilai_agun', models.CharField(blank=True, max_length=200, null=True)),
                ('ptasuran', models.CharField(blank=True, max_length=200, null=True)),
                ('alamat_asur1', models.CharField(blank=True, max_length=200, null=True)),
                ('alamat_asur2', models.CharField(blank=True, max_length=200, null=True)),
                ('kota_sur', models.CharField(blank=True, max_length=200, null=True)),
                ('tgl_proses', models.CharField(blank=True, max_length=200, null=True)),
                ('premi_asur', models.CharField(blank=True, max_length=200, null=True)),
                ('pembyr_premi', models.CharField(blank=True, max_length=200, null=True)),
                ('asur_cash', models.CharField(blank=True, max_length=200, null=True)),
                ('income', models.CharField(blank=True, max_length=200, null=True)),
                ('nama_ibu', models.CharField(blank=True, max_length=200, null=True)),
                ('selisih_bunga', models.CharField(blank=True, max_length=200, null=True)),
                ('kode_paket', models.CharField(blank=True, max_length=200, null=True)),
                ('biaya_lain', models.CharField(blank=True, max_length=200, null=True)),
                ('cara_biaya', models.CharField(blank=True, max_length=200, null=True)),
                ('periode_byr', models.CharField(blank=True, max_length=200, null=True)),
                ('pokok_awal_pk', models.CharField(blank=True, max_length=200, null=True)),
                ('tenor_awal', models.CharField(blank=True, max_length=200, null=True)),
                ('no_pk', models.CharField(blank=True, max_length=200, null=True)),
                ('net_dp_cash', models.CharField(blank=True, max_length=200, null=True)),
                ('asur_jiwa_ttl', models.CharField(blank=True, max_length=200, null=True)),
                ('asur_jiwa_cash', models.CharField(blank=True, max_length=200, null=True)),
            ],
            options={
                'db_table': '"ana"."permata_channeling_disbursement_fin"',
                'managed': False,
            },
        ),
        migrations.CreateModel(
            name='PermataDisbursementSipd',
            fields=[
                ('cdate', models.DateTimeField(auto_now_add=True)),
                ('udate', models.DateTimeField(auto_now=True)),
                (
                    'id',
                    models.AutoField(
                        db_column='permata_channeling_disbursement_sipd_id',
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                ('no_pin', models.CharField(blank=True, max_length=200, null=True)),
                ('nama_rekanan', models.CharField(blank=True, max_length=200, null=True)),
                ('alamat_bpr1', models.CharField(blank=True, max_length=200, null=True)),
                ('alamat_bpr2', models.CharField(blank=True, max_length=200, null=True)),
                ('kota', models.CharField(blank=True, max_length=200, null=True)),
                ('bukti_kepemilikan', models.CharField(blank=True, max_length=200, null=True)),
                ('no_jaminan', models.CharField(blank=True, max_length=200, null=True)),
                ('tgl', models.DateField(blank=True, null=True)),
                ('nama_pemilik', models.CharField(blank=True, max_length=200, null=True)),
                ('jumlah', models.CharField(blank=True, max_length=200, null=True)),
                ('no_rangka', models.CharField(blank=True, max_length=200, null=True)),
                ('no_mesin', models.CharField(blank=True, max_length=200, null=True)),
            ],
            options={
                'db_table': '"ana"."permata_channeling_disbursement_sipd"',
                'managed': False,
            },
        ),
        migrations.CreateModel(
            name='PermataDisbursementSlik',
            fields=[
                ('cdate', models.DateTimeField(auto_now_add=True)),
                ('udate', models.DateTimeField(auto_now=True)),
                (
                    'id',
                    models.AutoField(
                        db_column='permata_channeling_disbursement_slik_id',
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                ('loan_id', models.CharField(blank=True, max_length=200, null=True)),
                ('alamat_tempat_bekerja', models.CharField(blank=True, max_length=200, null=True)),
                ('yearly_income', models.CharField(blank=True, max_length=200, null=True)),
                ('jumlah_tanggungan', models.CharField(blank=True, max_length=200, null=True)),
                (
                    'status_perkawinan_debitur',
                    models.CharField(blank=True, max_length=200, null=True),
                ),
                ('nomor_ktp_pasangan', models.CharField(blank=True, max_length=200, null=True)),
                ('nama_pasangan', models.CharField(blank=True, max_length=200, null=True)),
                ('tanggal_lahir_pasangan', models.CharField(blank=True, max_length=200, null=True)),
                ('perjanjian_pisah_harta', models.CharField(blank=True, max_length=200, null=True)),
                ('fasilitas_kredit', models.CharField(blank=True, max_length=200, null=True)),
                ('take_over_dari', models.CharField(blank=True, max_length=200, null=True)),
                ('kode_jenis_pengguna', models.CharField(blank=True, max_length=200, null=True)),
                ('kode_bisa_usaha_slik', models.CharField(blank=True, max_length=200, null=True)),
                ('email', models.CharField(blank=True, max_length=200, null=True)),
                ('alamat_sesuai_domisili', models.CharField(blank=True, max_length=200, null=True)),
                ('kategori_debitur_umkm', models.CharField(blank=True, max_length=200, null=True)),
                (
                    'deskripsi_jenis_pengguna_kredit',
                    models.CharField(blank=True, max_length=200, null=True),
                ),
                ('pembiayaan_produktif', models.CharField(blank=True, max_length=200, null=True)),
                ('monthly_income', models.CharField(blank=True, max_length=200, null=True)),
            ],
            options={
                'db_table': '"ana"."permata_channeling_disbursement_slik"',
                'managed': False,
            },
        ),
        migrations.CreateModel(
            name='PermataPayment',
            fields=[
                ('cdate', models.DateTimeField(auto_now_add=True)),
                ('udate', models.DateTimeField(auto_now=True)),
                (
                    'id',
                    models.AutoField(
                        db_column='permata_channeling_payment_id', primary_key=True, serialize=False
                    ),
                ),
                ('loan_id', models.CharField(blank=True, max_length=200, null=True)),
                ('nama', models.CharField(blank=True, max_length=200, null=True)),
                ('tgl_bayar_end_user', models.DateField(blank=True, null=True)),
                ('payment_event_id', models.CharField(blank=True, max_length=200, null=True)),
                ('nilai_angsuran', models.CharField(blank=True, max_length=200, null=True)),
                ('denda', models.CharField(blank=True, max_length=200, null=True)),
                ('diskon_denda', models.CharField(blank=True, max_length=200, null=True)),
                ('tgl_terima_mf', models.DateField(blank=True, null=True)),
            ],
            options={
                'db_table': '"ana"."permata_channeling_payment"',
                'managed': False,
            },
        ),
        migrations.CreateModel(
            name='PermataReconciliation',
            fields=[
                ('cdate', models.DateTimeField(auto_now_add=True)),
                ('udate', models.DateTimeField(auto_now=True)),
                (
                    'id',
                    models.AutoField(
                        db_column='permata_channeling_reconciliation_id',
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                ('nopin', models.CharField(blank=True, max_length=200, null=True)),
                ('angsuran_ke', models.CharField(blank=True, max_length=200, null=True)),
                ('os_pokok', models.CharField(blank=True, max_length=200, null=True)),
                ('nama', models.CharField(blank=True, max_length=200, null=True)),
                ('dpd', models.CharField(blank=True, max_length=200, null=True)),
            ],
            options={
                'db_table': '"ana"."permata_channeling_reconciliation"',
                'managed': False,
            },
        ),
    ]
