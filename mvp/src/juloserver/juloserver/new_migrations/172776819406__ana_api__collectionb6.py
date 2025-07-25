# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2024-10-01 07:36
from __future__ import unicode_literals

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = []

    operations = [
        migrations.CreateModel(
            name='CollectionB6',
            fields=[
                ('cdate', models.DateTimeField(auto_now_add=True)),
                ('udate', models.DateTimeField(auto_now=True)),
                (
                    'id',
                    models.AutoField(
                        db_column='collection_b6_id', primary_key=True, serialize=False
                    ),
                ),
                ('assigned_to', models.CharField(blank=True, max_length=200, null=True)),
                ('assignment_datetime', models.DateTimeField(blank=True, null=True)),
                ('assignment_generated_date', models.DateField(blank=True, null=True)),
                ('customer_id', models.BigIntegerField(blank=True, null=True)),
                ('account_id', models.IntegerField(blank=True, null=True)),
                ('account_payment_id', models.BigIntegerField(blank=True, null=True)),
                ('nama_customer', models.CharField(blank=True, max_length=200, null=True)),
                ('nama_perusahaan', models.CharField(blank=True, max_length=200, null=True)),
                ('posisi_karyawan', models.CharField(blank=True, max_length=200, null=True)),
                ('dpd', models.IntegerField(blank=True, null=True)),
                ('total_denda', models.IntegerField(blank=True, null=True)),
                ('total_due_amount', models.IntegerField(blank=True, null=True)),
                ('total_outstanding', models.IntegerField(blank=True, null=True)),
                ('angsuran_ke', models.IntegerField(blank=True, null=True)),
                ('tanggal_jatuh_tempo', models.DateField(blank=True, null=True)),
                ('nama_pasangan', models.CharField(blank=True, max_length=200, null=True)),
                ('nama_kerabat', models.CharField(blank=True, max_length=200, null=True)),
                ('hubungan_kerabat', models.CharField(blank=True, max_length=200, null=True)),
                ('alamat', models.CharField(blank=True, max_length=200, null=True)),
                ('kota', models.CharField(blank=True, max_length=200, null=True)),
                ('jenis_kelamin', models.CharField(blank=True, max_length=200, null=True)),
                ('tgl_lahir', models.DateField(blank=True, null=True)),
                ('tgl_gajian', models.IntegerField(blank=True, null=True)),
                ('tujuan_pinjaman', models.CharField(blank=True, max_length=200, null=True)),
                ('tgl_upload', models.DateField(blank=True, null=True)),
                ('va_bca', models.CharField(blank=True, max_length=200, null=True)),
                ('va_permata', models.CharField(blank=True, max_length=200, null=True)),
                ('va_maybank', models.CharField(blank=True, max_length=200, null=True)),
                ('va_alfamart', models.CharField(blank=True, max_length=200, null=True)),
                ('va_indomaret', models.CharField(blank=True, max_length=200, null=True)),
                ('va_mandiri', models.CharField(blank=True, max_length=200, null=True)),
                ('tipe_produk', models.CharField(blank=True, max_length=200, null=True)),
                ('last_pay_date', models.CharField(blank=True, max_length=200, null=True)),
                ('last_pay_amount', models.CharField(blank=True, max_length=200, null=True)),
                ('partner_name', models.CharField(blank=True, max_length=200, null=True)),
                ('last_agent', models.CharField(blank=True, max_length=200, null=True)),
                ('last_call_status', models.CharField(blank=True, max_length=200, null=True)),
                ('refinancing_status', models.CharField(blank=True, max_length=200, null=True)),
                ('activation_amount', models.CharField(blank=True, max_length=200, null=True)),
                ('program_expiry_date', models.CharField(blank=True, max_length=200, null=True)),
                ('address_kodepos', models.CharField(blank=True, max_length=200, null=True)),
                ('phonenumber', models.CharField(blank=True, max_length=200, null=True)),
                ('mobile_phone_2', models.CharField(blank=True, max_length=200, null=True)),
                ('no_telp_pasangan', models.CharField(blank=True, max_length=200, null=True)),
                ('telp_perusahaan', models.CharField(blank=True, max_length=200, null=True)),
            ],
            options={
                'db_table': '"ana"."collection_b6"',
                'managed': False,
            },
        ),
    ]
