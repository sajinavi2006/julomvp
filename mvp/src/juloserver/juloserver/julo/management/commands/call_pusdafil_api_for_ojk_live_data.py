from __future__ import print_function
from builtins import chr
from builtins import str
from builtins import range
import logging
import sys
import csv
import base64
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.backends import default_backend
import json
from datetime import date
from datetime import datetime
import time

import requests
from django.db import connection
from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone

from juloserver.julo.exceptions import JuloException
from juloserver.julo.clients import get_julo_sentry_client

logger = logging.getLogger(__name__)
logger.addHandler(logging.StreamHandler(sys.stdout))

sentry_client = get_julo_sentry_client()

PUSDAFIL_MAX_RETRY = 3
PUSDAFIL_TABLES = (
    'reg_pengguna',
    'reg_lender',
    'reg_borrower',
    'pengajuan_pinjaman',
    'pengajuan_pemberian_pinjaman',
    'transaksi_pinjam_meminjam',
    'pembayaran_pinjaman'
)


def get_reg_pengunna_query(limit, offset, start_date, end_date):
    query = """select 810069 as id_penyelenggara
                        ,au.id id_pengguna
                        -- ,case when l.lender_id is not null then 1 when c.customer_id is not null then 2 end as kode_pengguna
                        ,case when l.lender_id is not null then 2 when c.customer_id is not null then 1 end jenis_pengguna
                        ,to_char(au.date_joined,'YYYY-MM-DD') tgl_registrasi
                        ,coalesce(a.fullname,l.lender_name) nama_pengguna
                        ,case when l.lender_id is not null then 3 when c.customer_id is not null then 1 end jenis_identitas
                        ,case when au.id = 514133 then '802965566015000' when c.customer_id is not null then a.ktp else '' end no_identitas
                        ,case when au.id = 514133 then '802965566015000' when c.customer_id is not null then null end no_npwp
                        ,case when l.lender_id is not null then 1 when c.customer_id is not null then 5 end id_jenis_badan_hukum
                        ,a.birth_place tempat_lahir
                        ,a.dob tgl_lahir
                        ,case when l.lender_id is not null then 3
                              when c.customer_id is not null and a.gender = 'Pria' then 1
                              when c.customer_id is not null and a.gender = 'Wanita' then 2 else 1
                              end id_jenis_kelamin
                        ,coalesce(case when length(a.address_street_num) > 1 then a.address_street_num else null end,'alamat kosong') alamat
                        , case when a.address_kabupaten = 'BEKASI' then 'e282'
                                when a.address_kabupaten = 'TANGERANG' then 'e311'
                                when a.address_kabupaten = 'Bekasi' then 'e282'
                                when a.address_kabupaten = 'JAKARTA TIMUR' then 'e320'
                                when a.address_kabupaten = 'JAKARTA SELATAN' then 'e319'
                                when a.address_kabupaten = 'JAKARTA BARAT' then 'e318'
                                when a.address_kabupaten = 'BOGOR' then 'e300'
                                when a.address_kabupaten = 'Tangerang' then 'e311'
                                when a.address_kabupaten = 'Jakarta Timur' then 'e320'
                                when a.address_kabupaten = 'Bandung' then 'e299'
                                when a.address_kabupaten = 'Bogor' then 'e300'
                                when a.address_kabupaten = 'Jakarta Selatan' then 'e319'
                                when a.address_kabupaten = 'Jakarta Barat' then 'e318'
                                when a.address_kabupaten = 'DEPOK' then 'e305'
                                when a.address_kabupaten = 'JAKARTA UTARA' then 'e317'
                                when a.address_kabupaten = 'BANDUNG' then 'e299'
                                when a.address_kabupaten = 'JAKARTA PUSAT' then 'e316'
                                when a.address_kabupaten = 'Surabaya' then 'e391'
                                when a.address_kabupaten = 'TANGERANG SELATAN' then 'e311'
                                when a.address_kabupaten = 'Depok' then 'e305'
                                when a.address_kabupaten = 'Jakarta Utara' then 'e317'
                                when a.address_kabupaten = 'Tangerang Selatan' then 'e311'
                                when a.address_kabupaten = 'DKI JAKARTA' then 'e316'
                                when a.address_kabupaten = 'Jakarta Pusat' then 'e316'
                                when a.address_kabupaten = 'SURABAYA' then 'e391'
                                when a.address_kabupaten = 'JAWA BARAT' then 'e282'
                                when a.address_kabupaten = 'Medan' then 'e471'
                                when a.address_kabupaten = 'Sidoarjo' then 'e363'
                                when a.address_kabupaten = 'Semarang' then 'e327'
                                when a.address_kabupaten = 'Karawang' then 'e284'
                                when a.address_kabupaten = 'Malang' then 'e373'
                                when a.address_kabupaten = 'BANTEN' then 'e313'
                                when a.address_kabupaten = 'Palembang' then 'e515'
                                when a.address_kabupaten = 'Batam' then 'e532'
                                when a.address_kabupaten = 'Sukabumi' then 'e286'
                                when a.address_kabupaten = 'Denpasar' then 'e693'
                                when a.address_kabupaten = 'Serang' then 'e310'
                                when a.address_kabupaten = 'MEDAN' then 'e471'
                                when a.address_kabupaten = 'Bandung Barat' then 'e298'
                                when a.address_kabupaten = 'Cirebon' then 'e293'
                                when a.address_kabupaten = 'BATAM' then 'e532'
                                when a.address_kabupaten = 'Makassar' then 'e634'
                                when a.address_kabupaten = 'Cimahi' then 'e304'
                                when a.address_kabupaten = 'Balikpapan' then 'e585'
                                when a.address_kabupaten = 'Manado' then 'e648'
                                when a.address_kabupaten = 'Bandar Lampung' then 'e545'
                                when a.address_kabupaten = 'Sleman' then 'e323'
                                when a.address_kabupaten = 'Badung' then 'e688'
                                when a.address_kabupaten = 'Deli Serdang' then 'e443'
                                when a.address_kabupaten = 'Pekanbaru' then 'e502'
                                when a.address_kabupaten = 'Cianjur' then 'e287'
                                when a.address_kabupaten = 'DENPASAR' then 'e693'
                                when a.address_kabupaten = 'Garut' then 'e291'
                                when a.address_kabupaten = 'Subang' then 'e297'
                                when a.address_kabupaten = 'Tasikmalaya' then 'e303'
                                when a.address_kabupaten = 'MANADO' then 'e648'
                                when a.address_kabupaten = 'Purwakarta' then 'e283'
                                when a.address_kabupaten = 'Gresik' then 'e362'
                                when a.address_kabupaten = 'Samarinda' then 'e584'
                                when a.address_kabupaten = 'BALIKPAPAN' then 'e585'
                                when a.address_kabupaten = 'Sumedang' then 'e289'
                                when a.address_kabupaten = 'Padang' then 'e486'
                                else 'e999'
                                end as id_kota
                        ,case
                                when a.address_provinsi = '31' then 'DKI JAKARTA'
                                when a.address_provinsi = '32' then 'Jawa Barat'
                                when a.address_provinsi = '32' then 'JAWA BARAT'
                                when a.address_provinsi = '31' then 'DKI Jakarta'
                                when a.address_provinsi = '36' then 'BANTEN'
                                when a.address_provinsi = '36' then 'Banten'
                                when a.address_provinsi = '35' then 'Jawa Timur'
                                when a.address_provinsi = '35' then 'JAWA TIMUR'
                                when a.address_provinsi = '12' then 'Sumatera Utara'
                                when a.address_provinsi = '33' then 'Jawa Tengah'
                                when a.address_provinsi = '51' then 'Bali'
                                when a.address_provinsi = '16' then 'Sumatera Selatan'
                                when a.address_provinsi = '21' then 'Kepulauan Riau'
                                when a.address_provinsi = '64' then 'Kalimantan Timur'
                                when a.address_provinsi = '12' then 'SUMATERA UTARA'
                                when a.address_provinsi = '21' then 'KEPULAUAN RIAU'
                                when a.address_provinsi = '73' then 'Sulawesi Selatan'
                                when a.address_provinsi = '71' then 'Sulawesi Utara'
                                when a.address_provinsi = '18' then 'Lampung'
                                when a.address_provinsi = '34' then 'DI Yogyakarta'
                                when a.address_provinsi = '14' then 'Riau'
                                when a.address_provinsi = '51' then 'BALI'
                                when a.address_provinsi = '71' then 'SULAWESI UTARA'
                                when a.address_provinsi = '64' then 'KALIMANTAN TIMUR'
                                when a.address_provinsi = '13' then 'Sumatera Barat'
                                else '99'
                                end as id_provinsi
                        ,a.address_kodepos kode_pos
                        ,9 id_agama
                        ,case when a.marital_status in ('Cerai','Janda / duda','Menikah') then 1
                              when a.marital_status in ('Lajang') then 2
                              when l.lender_id is not null then 3
                              else 4 end as id_status_perkawinan
                        ,case
                                when a.job_type = 'Tidak bekerja' then 8
                                when a.job_type = 'Staf rumah tangga' then 7
                                when a.job_type = 'Pengusaha' then 5
                                when a.job_type = 'Pekerja rumah tangga' then 7
                                when a.job_type = 'Pegawai swasta' then 4
                                when a.job_type = 'Pegawai negeri' then 1
                                when a.job_type = 'Mahasiswa' then 6
                                when a.job_type = 'Lainnya' then 7
                                when a.job_type = 'Ibu rumah tangga' then 8
                                when a.job_type = 'Freelance' then 7
                                when l.lender_id is not null then 9
                                else 10
                                end as id_pekerjaan
                        ,case
                            when a.job_industry = 'Admin / Finance / HR' then 'e62'
                            when a.job_industry = 'Sales / Marketing' then 'e40'
                            when a.job_industry = 'Pabrik / Gudang' then 'e12'
                            when a.job_industry = 'Service' then 'e70'
                            when a.job_industry = 'Transportasi' then 'e47'
                            when a.job_industry = 'Tehnik / Computer' then 'e67'
                            when a.job_industry = 'Kesehatan' then 'e64'
                            when a.job_industry = 'Konstruksi / Real Estate' then 'e56'
                            when a.job_industry = 'Perbankan' then 'e52'
                            when a.job_industry = 'Pendidikan' then 'e63'
                            when a.job_industry = 'Hukum / Security / Politik' then 'e71'
                            when a.job_industry = 'Design / Seni' then 'e72'
                            when a.job_industry = 'Entertainment / Event' then 'e46'
                            when a.job_industry = 'Perawatan Tubuh' then 'e70'
                            when a.job_industry = 'Staf Rumah Tangga' then 'e70'
                            when a.job_industry = 'Staf rumah tangga' then 'e70'
                            when a.job_industry = 'Media' then 'e47'
                            when a.job_industry = 'Pedagang' then 'e40'
                            else 'e99'
                            end as id_bidang_pekerjaan
                        ,3 id_pekerjaan_online
                        ,case
                            when a.monthly_income < 12500000 then '1'
                            when a.monthly_income >= 12000001 and a.monthly_income <= 50000000 then '2'
                            when a.monthly_income >= 50000001 and a.monthly_income <= 500000000 then '3'
                            when a.monthly_income >= 500000001 and a.monthly_income <= 50000000000 then '4'
                            when a.monthly_income > 50000000000 then '5'
                            else 'p7'
                            end as pendapatan
                        ,case
                            when current_date - a.job_start::date < 360 then 1
                            when current_date - a.job_start::date >= 360 and current_date - job_start::date <= 720 then 2
                            when current_date - a.job_start::date >= 720 and current_date - job_start::date <= 1080 then 3
                            when current_date - a.job_start::date >= 1080 then 4
                            when l.lender_id is not null then 5
                            else 6
                            end as pengalaman_kerja
                        ,case
                            when a.last_education = 'SD' then 1
                            when a.last_education = 'SLTP' then 2
                            when a.last_education = 'SLTA' then 3
                            when a.last_education = 'Diploma' then 4
                            when a.last_education = 'S1' then 5
                            when a.last_education = 'S2' then 6
                            when a.last_education = 'S3' then 7
                            when l.lender_id is not null then 8
                            else 9
                            end as id_pendidikan
                        ,l.poc_name nama_perwakilan
                        ,case when au.id = 514133 then '802965566015000' when c.customer_id is not null then null else '' end no_identitas_perwakilan
                        -- ,to_char(current_date,'YYYY-MM-DD') create_data
                from ops.auth_user au
                left join ops.customer c on c.auth_user_id = au.id
                left join ops.lender l on l.auth_user_id = au.id and l.lender_id = 1
                left join (
                    select *,row_number()over(partition by customer_id order by cdate) as rn
                    from ops.application
                    where length(fullname) >1 and length(ktp) > 1 and length(address_street_num) > 1
                ) a on a.customer_id = c.customer_id and a.rn = 1
        where (l.lender_id is not null or a.fullname is not null)
              and (au.date_joined >= '{start_date} 00:00:00 +07:00'
                   and au.date_joined <'{end_date} 00:00:00 +07:00')
        order by au.id asc
        limit {limit} offset {offset}""".format(limit=limit,
                                                offset=offset,
                                                start_date=start_date,
                                                end_date=end_date)

    return query


def reg_lender_query(limit, offset, start_date):
    query = """select 810069 id_penyelenggara
                ,au.id id_pengguna
                ,l.lender_id id_lender
                ,0 id_negara_domisili
                ,null id_kewarganegaraan
                ,'Lain-Lain' sumber_dana
                from ops.auth_user au
                join ops.lender l on l.auth_user_id = au.id
                where l.lender_id = 1
                    and au.date_joined >= '{start_date} 00:00:00 +07:00'
                order by au.id asc
                limit {limit} offset {offset}""".format(limit=limit, offset=offset, start_date=start_date)
    return query


def reg_borrower_query(limit, offset, start_date, end_date):
    query = """select
                    810069 id_penyelenggara
                    ,au.id id_pengguna
                    ,c.customer_id id_borrower
                    ,0 as total_aset
                    ,case when a.home_status in ('Milik sendiri, lunas','Milik sendiri, mencicil') then 1 else 2 end status_kepemilikan_rumah
                from ops.auth_user au
                join ops.customer c on c.auth_user_id = au.id
                join (
                    select *,row_number()over(partition by customer_id order by cdate) as rn
                    from ops.application
                    where length(fullname) > 1 and length(ktp) >1 and length(address_street_num) > 1
                ) a on a.customer_id = c.customer_id and a.rn = 1
                where (au.date_joined >= '{start_date} 00:00:00 +07:00'
                   and au.date_joined <'{end_date} 00:00:00 +07:00')
                order by au.id asc
                limit {limit} offset {offset}""".format(limit=limit,
                                                        offset=offset,
                                                        start_date=start_date,
                                                        end_date=end_date)
    return query


def pengajuan_pinjaman_query(limit, offset, start_date, end_date):
    query = """select
                810069 id_penyelenggara
                ,a.application_xid id_pinjaman
                ,a.customer_id id_borrower
                ,2 id_syariah
                ,case when a.application_status_code in (141,163,172) then 1
                    when a.application_status_code in (133,134,135) then 2
                    when a.application_status_code in (180) then 3
                    when a.application_status_code in (137,139) then 6
                    else 0
                    end id_status_pengajuan_pinjaman
                ,case when x160.application_id is not null
                        then substring(pline.product_line_type,1,length(pline.product_line_type)-1)
                    else pline.product_line_type
                    end as nama_pinjaman
                ,to_char(a.cdate::date,'YYYY-MM-DD') tgl_pengajuan_pinjaman
                ,a.loan_amount_request nilai_permohonan_pinjaman
                ,a.loan_duration_request jangka_waktu_pinjaman
                ,3 satuan_jangka_waktu_pinjaman
                ,'e0' penggunaan_pinjaman
                ,2 agunan
                ,8 jenis_agunan
                ,0 rasio_pinjaman_nilai_agunan
                ,'' permintaan_jaminan
                ,0 rasio_pinjaman_aset
                ,a.total_current_debt cicilan_bulan
                ,coalesce(cs.score,'B-') rating_pengajuan_pinjaman
                ,0 nilai_plafond
                ,a.loan_amount_request nilai_pengajuan_pinjaman
                ,pl.interest_rate suku_bunga_pinjaman
                ,4 satuan_suku_bunga_pinjaman
                ,1 jenis_bunga
                ,case when x160.application_id is not null 
                        then to_char(x160.ts,'YYYY-MM-DD')
                    else to_char(x211.ts,'YYYY-MM-DD')
                    end as tgl_mulai_publikasi_pinjaman
                ,case when x160.application_id is not null 
                        then l.fund_transfer_ts::date - x160.ts::date 
                    else l.fund_transfer_ts::date - x211.ts::date 
                    end as rencana_jangka_waktu_publikasi
                ,case when x160.application_id is not null 
                    then l.fund_transfer_ts::date - x160.ts::date
                    else  l.fund_transfer_ts::date - x211.ts::date
                    end as realisasi_jangka_waktu_publikasi
                ,to_char(l.fund_transfer_ts,'YYYY-MM-DD') tgl_mulai_pendanaan
                ,coalesce(a.application_number,1) frekuensi_pinjaman
            from ops.application a
            left join ops.credit_score cs on cs.application_id = a.application_id
            join ops.product_line pline on pline.product_line_code = a.product_line_code
            join ops.loan l on l.application_id = a.application_id or a.account_id = l.account_id
            join ops.product_lookup pl on pl.product_code = l.product_code
            left join (
                select application_id,min(cdate) as ts
                from ops.application_history
                where status_new in (160,148)
                group by 1
            )x160 on x160.application_id = a.application_id
            left join (
                select loan_id,min(cdate) as ts
                from ops.loan_history
                where status_new = 211
                group by 1
            )x211 on x211.loan_id = l.loan_id
            join (
                select loan_id,max(due_date) as max_due_date
                from ops.payment
                group by 1
            )p on p.loan_id = l.loan_id
            where
                a.application_status_code in (180,190)
                and l.loan_status_code >=220
                and length(a.ktp) > 1 and length(a.fullname) > 1 and length(a.address_street_num) > 1
                and (a.cdate >= '{start_date} 00:00:00 +07:00'
                   and a.cdate <'{end_date} 00:00:00 +07:00')
                and (x211.loan_id is not null or x160.application_id is not null)
            order by a.application_id asc
            limit {limit} offset {offset}""".format(limit=limit,
                                                    offset=offset,
                                                    start_date=start_date,
                                                    end_date=end_date)
    return query


def pengajuan_pemberian_pinjaman_query(limit, offset, start_date, end_date):
    query = """select
            810069 id_penyelenggara
            ,a.application_xid id_pinjaman
            ,a.customer_id id_borrower
            ,le.lender_id id_lender
            ,le.pks_number no_perjanjian_lender
            ,to_char(l.cdate,'YYYY-MM-DD') tgl_perjanjian_lender
            ,to_char(l.cdate,'YYYY-MM-DD') tgl_penawaran_pemberian_pinjaman
            ,l.loan_amount nilai_penawaran_pinjaman
            ,l.loan_amount nilai_penawaran_disetujui
            ,lba.account_number no_va_lender
        from ops.application a
        join ops.loan l on l.application_id = a.application_id or l.account_id = a.account_id
        join ops.lender le on le.lender_id = 1
        join ops.lender_bank_account lba on lba.lender_id = le.lender_id and lba.bank_account_type = 'repayment_va'
        where length(a.ktp) > 1 and length(a.fullname) > 1 and length(a.address_street_num) > 1
            and  a.application_status_code in (180,190)
            and (a.cdate >= '{start_date} 00:00:00 +07:00'
                       and a.cdate < '{end_date} 00:00:00 +07:00')
        order by a.application_id asc
        limit {limit} offset {offset}""".format(limit=limit, offset=offset,
                                                start_date=start_date,
                                                end_date=end_date)
    return query


def transaksi_pinjam_meminjam_query(limit, offset, start_date, end_date):
    query = """select
                810069 id_penyelenggara
                ,a.application_xid id_pinjaman
                ,a.customer_id id_borrower
                ,le.lender_id id_lender
                ,a.application_xid id_transaksi
                ,a.application_xid no_perjanjian_borrower
                ,to_char(l.sphp_accepted_ts,'YYYY-MM-DD') tgl_perjanjian_borrower
                ,l.loan_amount nilai_pendanaan
                ,pl.interest_rate suku_bunga_pinjaman
                ,4 satuan_suku_bunga_pinjaman
                ,case when a.product_line_code in (10,11) then 1 else 2 end as id_jenis_pembayaran
                ,3 id_frekuensi_pembayaran
                ,l.installment_amount nilai_angsuran
                ,null objek_jaminan
                ,l.loan_duration jangka_waktu_pinjaman
                ,3 satuan_jangka_waktu_pinjaman
                ,to_char(p.first_due_date, 'YYYY-MM-DD') tgl_jatuh_tempo
                ,to_char(l.fund_transfer_ts,'YYYY-MM-DD') tgl_pendanaan
                ,to_char(l.fund_transfer_ts,'YYYY-MM-DD') tgl_penyaluran_dana
                ,lba.account_number no_ea_transaksi
                ,coalesce(a.application_number,0) frekuensi_pendanaan
        from ops.application a
        join ops.loan l on l.application_id = a.application_id or l.account_id = a.account_id
        join ops.product_lookup pl on pl.product_code = l.product_code
        join ops.lender le on le.lender_id = 1
        join ops.lender_bank_account lba on lba.lender_id = le.lender_id and lba.bank_account_type = 'disbursement_va'
        join (
            select loan_id
                    ,min(due_date) first_due_date
            from ops.payment
            group by 1
        ) p on p.loan_id = l.loan_id
        --for daily update
        left join (
            select distinct application_id
            from ops.application_history
            where status_new = 180
            and (cdate >= '{start_date} 00:00:00 +07:00'
                       and cdate < '{end_date} 00:00:00 +07:00')
        ) x180 on x180.application_id = a.application_id
        left join (
            select distinct loan_id
            from ops.loan_history
            where status_new = 220
            and (cdate >= '{start_date} 00:00:00 +07:00'
                       and cdate < '{end_date} 00:00:00 +07:00')
        ) x220 on x220.loan_id = l.loan_id
        where a.application_status_code in (180,190)
            and (x220.loan_id is not null or x180.application_id is not null)
            and length(a.ktp) > 1 and length(a.fullname) > 1 and length(a.address_street_num) > 1
        order by l.loan_id asc
        limit {limit} offset {offset}""".format(limit=limit,
                                                offset=offset,
                                                start_date=start_date,
                                                end_date=end_date)
    return query


def pembayaran_pinjaman_query(limit, offset, start_date, end_date):
    query = """select
                810069 id_penyelenggara
                ,a.application_xid id_pinjaman
                ,a.customer_id id_borrower
                ,le.lender_id id_lender
                ,a.application_xid id_transaksi
                ,p.payment_id id_pembayaran
                ,p.due_date tgl_jatuh_tempo
                ,lead(p.due_date) over(partition by l.loan_id order by p.payment_id) tgl_jatuh_tempo_selanjutnya
                ,p.paid_date tgl_pembayaran_borrower
                ,p.paid_date tgl_pembayaran_penyelenggara
                ,case when p.paid_amount >= p.installment_principal or l.loan_status_code in (210,234,235,236,237,240,260) then 0
                      when p.paid_amount <  p.installment_principal then p.installment_principal - p.paid_amount
                      end as sisa_pinjaman_berjalan
                ,case when l.loan_status_code in (220,230,231,250) then 1
                      when l.loan_status_code in (232,233) then 2
                      when l.loan_status_code in (210,234,235,236,237,240,260) then 3
                      end as id_status_pinjaman
                ,p.paid_date tgl_pelunasan_borrower
                ,p.paid_date tgl_pelunasan_penyelenggara
                ,p.late_fee_amount denda
                ,p.paid_amount nilai_pembayaran
            from ops.application a
            join ops.loan l on l.application_id = a.application_id or a.account_id = l.account_id
            join ops.payment p on p.loan_id = l.loan_id
            join ops.lender le on le.lender_id = 1
            join (
                select distinct loan_id
                from ops.payment p
                join ops.payment_event pe on pe.payment_id = p.payment_id
                where (pe.cdate >= '{start_date} 00:00:00 +07:00'
                       and pe.cdate < '{end_date} 00:00:00 +07:00')
            ) ph on ph.loan_id = l.loan_id
            where a.application_status_code in (180,190)
                and length(a.ktp) > 1 and length(a.fullname) > 1 and length(a.address_street_num) > 1
                and p.paid_amount != 0
            order by p.payment_id asc
            limit {limit} offset {offset}""".format(limit=limit,
                                                    offset=offset,
                                                    start_date=start_date,
                                                    end_date=end_date)
    return query


def encrypt(raw):
    BS = 16
    pad = lambda s: s + (BS - len(s) % BS) * chr(BS - len(s) % BS)
    raw = pad(raw)
    key = b'WmZq3t6w9z$C&F)J@NcRfUjXn2r5u7x!'
    iv = b'ijzh84t1w9xa56s9'
    backend = default_backend()
    cipher = Cipher(algorithms.AES(key), modes.CBC(iv), backend)
    encryptor = cipher.encryptor()
    en = encryptor.update(raw.encode('utf8'))
    return base64.b64encode(base64.b64encode(en) + b'::' + iv)


def chunks(lst, n):
    """Yield successive n-sized chunks from lst."""
    for i in range(0, len(lst), n):
        yield lst[i:i + n]


def make_api_call_ojk(name, chunked_data, chunk_index):
    data = {}
    raw = json.dumps(chunked_data)
    data[name] = encrypt(raw)

    url = 'https://pusdafil.ojk.go.id/PusdafilAPI/pelaporanharian'
    retry_count = 1
    while True:
        try:
            response = requests.post(url, data, auth=('pusdafil@julo.co.id', '88Julo882020'))
            process_response(response, name, chunk_index)
            return
        except Exception as e:
            error = str(e)
            if 'Connection aborted' in error and retry_count <= PUSDAFIL_MAX_RETRY:
                time.sleep(pow(3, retry_count))
            else:
                err_msg = "POST to pusdafil url {} fails:  {}".format(
                    url, error)
                raise JuloException(err_msg)
            retry_count += 1


def process_response(response, table_name, chunk_index):
    if response.status_code in [200, 201]:
        response_body = response.json()

        # log response for troubleshooting TODO : can remove in prod automation
        log_response("response_%s" % table_name, response_body)

        if response_body.get('request_status') != 200:
            message_list = [{"error_message": message} for message in response_body.get("message")]
            log_failures("errors_%s" % table_name, len(response_body.get("message")), chunk_index, message_list)
            raise JuloException(
                'Error in response table : %s  api. status: %s response data: %s' % (
                    table_name, response_body.get('request_status'), response_body))
        else:
            # check for errors in submission
            response_data_index = PUSDAFIL_TABLES.index(table_name)
            if response_data_index in range(7):
                response_node = response_body.get('data')[response_data_index]
                if response_node['error'] is True:
                    raise JuloException(
                        'Error in response table : %s , response data: %s' % (
                            table_name, response_node['message']))
        return response


def create_reg_pengguna(
        id_penyelenggara, id_pengguna, jenis_pengguna, tgl_registrasi,
        nama_pengguna, jenis_identitas, no_identitas, no_npwp, id_jenis_badan_hukum,
        tempat_lahir, tgl_lahir, id_jenis_kelamin, alamat, id_kota, id_provinsi, kode_pos,
        id_agama, id_status_perkawinan, id_pekerjaan, id_bidang_pekerjaan, id_pekerjaan_online,
        pendapatan, pengalaman_kerja, id_pendidikan, nama_perwakilan, no_identitas_perwakilan):

    if isinstance(tgl_lahir, date):
        try:
            tgl_lahir = tgl_lahir.strftime("%Y-%m-%d")
        except ValueError:
            tgl_lahir = ''

    if isinstance(tgl_registrasi, date):
        tgl_registrasi = tgl_registrasi.strftime("%Y-%m-%d")

    if tempat_lahir:
        tempat_lahir = tempat_lahir[:50] if len(tempat_lahir) > 50 else tempat_lahir

    reg_pengguna = {
        'id_penyelenggara': str(id_penyelenggara), 'id_pengguna': str(id_pengguna), 'jenis_pengguna': jenis_pengguna,
        'tgl_registrasi': tgl_registrasi, 'nama_pengguna': nama_pengguna,
        'jenis_identitas': jenis_identitas, 'no_identitas': no_identitas,
        'no_npwp': no_npwp, 'id_jenis_badan_hukum': id_jenis_badan_hukum, 'tempat_lahir': tempat_lahir,
        'tgl_lahir': tgl_lahir, 'id_jenis_kelamin': id_jenis_kelamin,
        'alamat': alamat, 'id_kota': id_kota, 'id_provinsi': id_provinsi, 'kode_pos': kode_pos,
        'id_agama': id_agama, 'id_status_perkawinan': id_status_perkawinan,
        'id_pekerjaan': id_pekerjaan, 'id_bidang_pekerjaan': id_bidang_pekerjaan,
        'id_pekerjaan_online': id_pekerjaan_online, 'pendapatan': str(pendapatan),
        'pengalaman_kerja': pengalaman_kerja, 'id_pendidikan': id_pendidikan,
        'nama_perwakilan': nama_perwakilan, 'no_identitas_perwakilan': str(no_identitas_perwakilan)
    }
    return reg_pengguna


def create_reg_borrower(
        id_penyelenggara, id_pengguna, id_borrower, total_aset, status_kepemilikan_rumah):
    reg_borrower = {
        'id_penyelenggara': str(id_penyelenggara),
        'id_pengguna': str(id_pengguna),
        'id_borrower': str(id_borrower),
        'total_aset': total_aset,
        'status_kepemilikan_rumah': status_kepemilikan_rumah
    }
    return reg_borrower


def create_reg_lender(
        id_penyelenggara, id_pengguna, id_lender, id_negara_domisili, id_kewarganegaraan,
        sumber_dana):
    reg_lender = {
        'id_penyelenggara': str(id_penyelenggara),
        'id_pengguna': str(id_pengguna),
        'id_lender': str(id_lender),
        'id_negara_domisili': id_negara_domisili,
        'id_kewarganegaraan': id_kewarganegaraan,
        'sumber_dana': str(sumber_dana)
    }
    return reg_lender


def create_pengajuan_pinjaman(
    id_penyelenggara, id_pinjaman, id_borrower, id_syariah, id_status_pengajuan_pinjaman,
    nama_pinjaman, tgl_pengajuan_pinjaman, nilai_permohonan_pinjaman, jangka_waktu_pinjaman,
    satuan_jangka_waktu_pinjaman, penggunaan_pinjaman, agunan, jenis_agunan, rasio_pinjaman_nilai_agunan,
    permintaan_jaminan, rasio_pinjaman_aset, cicilan_bulan, rating_pengajuan_pinjaman, nilai_plafond,
    nilai_pengajuan_pinjaman, suku_bunga_pinjaman, satuan_suku_bunga_pinjaman, jenis_bunga, tgl_mulai_publikasi_pinjaman,
    rencana_jangka_waktu_publikasi, realisasi_jangka_waktu_publikasi, tgl_mulai_pendanaan, frekuensi_pinjaman):
    pengajuan_pinjaman = {
        'id_penyelenggara': str(id_penyelenggara), 'id_pinjaman': str(id_pinjaman), 'id_borrower': str(id_borrower),
        'id_syariah': id_syariah, 'id_status_pengajuan_pinjaman': id_status_pengajuan_pinjaman,
        'nama_pinjaman': nama_pinjaman, 'tgl_pengajuan_pinjaman': tgl_pengajuan_pinjaman,
        'nilai_permohonan_pinjaman': nilai_permohonan_pinjaman, 'jangka_waktu_pinjaman': jangka_waktu_pinjaman,
        'satuan_jangka_waktu_pinjaman': satuan_jangka_waktu_pinjaman, 'penggunaan_pinjaman': penggunaan_pinjaman,
        'agunan': agunan, 'jenis_agunan': jenis_agunan, 'rasio_pinjaman_nilai_agunan': rasio_pinjaman_nilai_agunan,
        'permintaan_jaminan': permintaan_jaminan, 'rasio_pinjaman_aset': rasio_pinjaman_aset, 'cicilan_bulan': cicilan_bulan,
        'rating_pengajuan_pinjaman': rating_pengajuan_pinjaman, 'nilai_plafond': nilai_plafond,
        'nilai_pengajuan_pinjaman': nilai_pengajuan_pinjaman, 'suku_bunga_pinjaman': suku_bunga_pinjaman,
        'satuan_suku_bunga_pinjaman': satuan_suku_bunga_pinjaman, 'jenis_bunga': jenis_bunga,
        'tgl_mulai_publikasi_pinjaman': tgl_mulai_publikasi_pinjaman, 'rencana_jangka_waktu_publikasi': rencana_jangka_waktu_publikasi,
        'realisasi_jangka_waktu_publikasi': realisasi_jangka_waktu_publikasi, 'tgl_mulai_pendanaan': tgl_mulai_pendanaan,
        'frekuensi_pinjaman': frekuensi_pinjaman
    }
    return pengajuan_pinjaman


def create_pengajuan_pemberian_pinjaman(
    id_penyelenggara, id_pinjaman, id_borrower, id_lender, no_perjanjian_lender, tgl_perjanjian_lender,
    tgl_penawaran_pemberian_pinjaman, nilai_penawaran_pinjaman, nilai_penawaran_disetujui, no_va_lender):
    pengajuan_pemberian_pinjaman = {
        'id_penyelenggara': str(id_penyelenggara),
        'id_pinjaman': str(id_pinjaman),
        'id_borrower': str(id_borrower),
        'id_lender': str(id_lender),
        'no_perjanjian_lender': str(no_perjanjian_lender),
        'tgl_perjanjian_lender': tgl_perjanjian_lender,
        'tgl_penawaran_pemberian_pinjaman': tgl_penawaran_pemberian_pinjaman,
        'nilai_penawaran_pinjaman': nilai_penawaran_pinjaman,
        'nilai_penawaran_disetujui': nilai_penawaran_disetujui,
        'no_va_lender': str(no_va_lender)
    }
    return pengajuan_pemberian_pinjaman


def create_transaksi_pinjam_meminjam(
    id_penyelenggara, id_pinjaman, id_borrower, id_lender, id_transaksi, no_perjanjian_borrower, tgl_perjanjian_borrower,
    nilai_pendanaan, suku_bunga_pinjaman, satuan_suku_bunga_pinjaman, id_jenis_pembayaran, id_frekuensi_pembayaran,
    nilai_angsuran, objek_jaminan, jangka_waktu_pinjaman, satuan_jangka_waktu_pinjaman, tgl_jatuh_tempo, tgl_pendanaan,
    tgl_penyaluran_dana, no_ea_transaksi, frekuensi_pendanaan):

    if isinstance(tgl_perjanjian_borrower, date):
        tgl_perjanjian_borrower = tgl_perjanjian_borrower.strftime("%Y-%m-%d")
    if isinstance(tgl_jatuh_tempo, date):
        tgl_jatuh_tempo = tgl_jatuh_tempo.strftime("%Y-%m-%d")
    if isinstance(tgl_pendanaan, date):
        tgl_pendanaan = tgl_pendanaan.strftime("%Y-%m-%d")
    if isinstance(tgl_penyaluran_dana, date):
        tgl_penyaluran_dana = tgl_penyaluran_dana.strftime("%Y-%m-%d")

    transaksi_pinjam_meminjam = {
        'id_penyelenggara': str(id_penyelenggara), 'id_pinjaman': str(id_pinjaman), 'id_borrower': str(id_borrower),
        'id_lender': str(id_lender), 'id_transaksi': str(id_transaksi), 'no_perjanjian_borrower': str(no_perjanjian_borrower),
        'tgl_perjanjian_borrower': tgl_perjanjian_borrower, 'nilai_pendanaan': nilai_pendanaan,
        'suku_bunga_pinjaman': suku_bunga_pinjaman,'satuan_suku_bunga_pinjaman': satuan_suku_bunga_pinjaman,
        'id_jenis_pembayaran': id_jenis_pembayaran, 'id_frekuensi_pembayaran': id_frekuensi_pembayaran,
        'nilai_angsuran': nilai_angsuran, 'objek_jaminan': str(objek_jaminan), 'jangka_waktu_pinjaman': jangka_waktu_pinjaman,
        'satuan_jangka_waktu_pinjaman': satuan_jangka_waktu_pinjaman, 'tgl_jatuh_tempo': tgl_jatuh_tempo,
        'tgl_pendanaan': tgl_pendanaan,'tgl_penyaluran_dana': tgl_penyaluran_dana,
        'no_ea_transaksi': no_ea_transaksi,'frekuensi_pendanaan': frekuensi_pendanaan
    }
    return transaksi_pinjam_meminjam


def create_pembayaran_pinjaman(
        id_penyelenggara, id_pinjaman, id_borrower, id_lender, id_transaksi, id_pembayaran,
        tgl_jatuh_tempo, tgl_jatuh_tempo_selanjutnya, tgl_pembayaran_borrower, tgl_pembayaran_penyelenggara,
        sisa_pinjaman_berjalan, id_status_pinjaman, tgl_pelunasan_borrower, tgl_pelunasan_penyelenggara, denda, nilai_pembayaran):

    if isinstance(tgl_jatuh_tempo, date):
        tgl_jatuh_tempo = tgl_jatuh_tempo.strftime("%Y-%m-%d")
    if isinstance(tgl_jatuh_tempo_selanjutnya, date):
        tgl_jatuh_tempo_selanjutnya = tgl_jatuh_tempo_selanjutnya.strftime("%Y-%m-%d")
    if isinstance(tgl_pembayaran_borrower, date):
        tgl_pembayaran_borrower = tgl_pembayaran_borrower.strftime("%Y-%m-%d")
    if isinstance(tgl_pembayaran_penyelenggara, date):
        tgl_pembayaran_penyelenggara = tgl_pembayaran_penyelenggara.strftime("%Y-%m-%d")
    if isinstance(tgl_pelunasan_borrower, date):
        tgl_pelunasan_borrower = tgl_pelunasan_borrower.strftime("%Y-%m-%d")
    if isinstance(tgl_pelunasan_penyelenggara, date):
        tgl_pelunasan_penyelenggara = tgl_pelunasan_penyelenggara.strftime("%Y-%m-%d")

    pembayaran_pinjaman = {
        'id_penyelenggara': str(id_penyelenggara),
        'id_pinjaman': str(id_pinjaman),
        'id_borrower': str(id_borrower),
        'id_lender': str(id_lender),
        'id_transaksi': str(id_transaksi),
        'id_pembayaran': str(id_pembayaran),
        'tgl_jatuh_tempo': tgl_jatuh_tempo,
        'tgl_jatuh_tempo_selanjutnya': tgl_jatuh_tempo_selanjutnya,
        'tgl_pembayaran_borrower': tgl_pembayaran_borrower,
        'tgl_pembayaran_penyelenggara': tgl_pembayaran_penyelenggara,
        'sisa_pinjaman_berjalan': sisa_pinjaman_berjalan,
        'id_status_pinjaman': id_status_pinjaman,
        'tgl_pelunasan_borrower': tgl_pelunasan_borrower,
        'tgl_pelunasan_penyelenggara': tgl_pelunasan_penyelenggara,
        'denda': denda,
        'nilai_pembayaran': nilai_pembayaran
    }
    return pembayaran_pinjaman


def log_failures(filename, count, chunk_index, data_list):
    pusdafil_upload_failures_filename = ''.join([
        settings.MEDIA_ROOT,
        filename,
        "_%s" % timezone.localtime(timezone.now()).date(),
        "_%s" % count,
        "_%s" % chunk_index,
        ".csv"])
    with open(pusdafil_upload_failures_filename, mode='w') as csv_file:
        fieldnames = list(data_list[0].keys())
        writer = csv.DictWriter(csv_file, fieldnames=fieldnames)
        print({
            "pusdafil_upload_failures_filename": pusdafil_upload_failures_filename,
            "status": "writing"
        })
        writer.writeheader()

        for row in data_list:
            writer.writerow(row)


def log_response(filename, response_data):
    pusdafil_upload_response_filename = ''.join([
        settings.MEDIA_ROOT,
        'response/',
        filename,
        "_%s" % timezone.localtime(timezone.now()).date(),
        ".csv"])

    # serialise json
    response_object = json.dumps(response_data, indent=4)
    print({
        "pusdafil_upload_response_filename": pusdafil_upload_response_filename,
        "status": "writing"
    })

    with open(pusdafil_upload_response_filename, 'a') as log_response_file:
        log_response_file.write(response_object)
        log_response_file.write('\n=================================================\n')


class Command(BaseCommand):
    help = 'call ojk api with production data'

    def add_arguments(self, parser):
        parser.add_argument("-s",
                            "--start_date",
                            help="Define start date - format YYYY-MM-DD",
                            required=True,
                            type=self.valid_date)

        parser.add_argument('-e', '--end_date', type=self.valid_date, help='Define end date')

    def valid_date(self, date):
        try:
            datetime.strptime(date, '%Y-%m-%d')
            return date
        except ValueError:
            self.stdout.write(self.style.ERROR("Incorrect date format, should be YYYY-MM-DD"))
            sys.exit(1)

    def handle(self, *args, **options):

        max_num = 3000

        start_date = options['start_date']
        end_date = options['end_date']
        ########################################################################
        increment = 9000
        total = 0
        table_name = 'reg_pengguna'

        while total < 2500000:  # TODO: refactor to get total based on query's count
            with connection.cursor() as cursor:
                cursor.execute(get_reg_pengunna_query(increment, total, start_date, end_date))
                reg_pengguna_data = cursor.fetchall()

            reg_pengguna_list = []

            if len(reg_pengguna_data) == 0:
                self.stdout.write(self.style.WARNING(
                    "No more data for %s total: %s" % (table_name, total)
                ))
                break

            for reg_pen in reg_pengguna_data:
                reg_pengguna = create_reg_pengguna(
                    reg_pen[0], reg_pen[1], reg_pen[2], reg_pen[3], reg_pen[4], reg_pen[5],
                    reg_pen[6], reg_pen[7], reg_pen[8], reg_pen[9], reg_pen[10], reg_pen[11],
                    reg_pen[12], reg_pen[13], reg_pen[14], reg_pen[15], reg_pen[16], reg_pen[17],
                    reg_pen[18], reg_pen[19], reg_pen[20], reg_pen[21], reg_pen[22], reg_pen[23],
                    reg_pen[24], reg_pen[25])
                reg_pengguna_list.append(reg_pengguna)
            chunked_reg_pengguna = list(chunks(reg_pengguna_list, max_num))
            chunk_index = 0
            for chunk in chunked_reg_pengguna:
                chunk_index += 1
                try:
                    make_api_call_ojk(table_name, chunk, chunk_index)
                    self.stdout.write(self.style.SUCCESS(
                        "Completed API call for %s count: %s total: %s" % (
                            table_name, len(chunk), total)))
                except Exception as e:
                    sentry_client.captureException()
                    self.stdout.write(self.style.ERROR("Error in response %s count: %s total: %s" % (
                        table_name, len(chunk), total)))
                    log_failures("data_%s" % table_name, total, chunk_index, chunk)
            total += increment
        ########################################################################
        # Already send data only 1 lender row

        increment = 1
        total = 0
        table_name = 'reg_lender'

        while total < 0:  # TODO: refactor to get total based on query's count
            with connection.cursor():
                cursor.execute(reg_lender_query(increment, total, start_date, end_date))
                reg_lender_data = cursor.fetchall()

            reg_lender_list = []

            if len(reg_lender_data) == 0:
                self.stdout.write(self.style.WARNING(
                    "No more data for %s total: %s" % (table_name, total)
                ))
                break

            for reg_len in reg_lender_data:
                reg_lender = create_reg_lender(
                    reg_len[0], reg_len[1], reg_len[2], reg_len[3], reg_len[4], reg_len[5]
                )
                reg_lender_list.append(reg_lender)
            chunked_reg_lender = list(chunks(reg_lender_list, max_num))
            chunk_index = 0
            for chunk in chunked_reg_lender:
                chunk_index += 1
                try:
                    make_api_call_ojk(table_name, chunk, chunk_index)
                    self.stdout.write(self.style.SUCCESS(
                        "Completed API call for %s count: %s total: %s" % (
                            table_name, len(chunk), total)))
                except Exception as e:
                    sentry_client.captureException()
                    self.stdout.write(self.style.ERROR("Error in response for %s count: %s total: %s" % (
                            table_name, len(chunk), total)))
                    log_failures("data_%s" % table_name, total, chunk_index, chunk)
            total += increment

        ########################################################################
        increment = 10000
        total = 0
        table_name = 'reg_borrower'

        while total < 2500000:  # TODO: refactor to get total based on query's count
            with connection.cursor() as cursor:
                cursor.execute(reg_borrower_query(increment, total, start_date, end_date))
                reg_borrower_data = cursor.fetchall()

            if len(reg_borrower_data) == 0:
                self.stdout.write(self.style.WARNING(
                    "No more data for %s total: %s" % (table_name, total)
                ))
                break

            reg_borrower_list = []
            for reg_bor in reg_borrower_data:
                reg_borrower = create_reg_borrower(
                    reg_bor[0], reg_bor[1], reg_bor[2], reg_bor[3], reg_bor[4]
                )
                reg_borrower_list.append(reg_borrower)
            chunked_reg_borrower = list(chunks(reg_borrower_list, max_num))
            chunk_index = 0
            for chunk in chunked_reg_borrower:
                chunk_index += 1
                try:
                    make_api_call_ojk(table_name, chunk, chunk_index)
                    self.stdout.write(self.style.SUCCESS(
                        "Completed API call for %s count: %s total: %s" % (
                            table_name, len(chunk), total)))
                except Exception as e:
                    sentry_client.captureException()
                    self.stdout.write(self.style.ERROR("Error in response for %s count: %s total: %s" % (
                        table_name, len(chunk), total)))
                    log_failures("data_%s" % table_name, total, chunk_index, chunk)

                total += increment

        ########################################################################
        increment = 10000
        total = 0
        table_name = 'pengajuan_pinjaman'

        while total < 1000000:  # TODO: refactor to get total based on query's count
            with connection.cursor() as cursor:
                cursor.execute(pengajuan_pinjaman_query(increment, total, start_date, end_date))
                pengajuan_pinjaman_data = cursor.fetchall()

            if len(pengajuan_pinjaman_data) == 0:
                self.stdout.write(self.style.WARNING(
                    "No more data for %s total: %s" % (table_name, total)
                ))
                break

            pengajuan_pinjaman_list = []
            for pen_pin in pengajuan_pinjaman_data:
                pengajuan_pinjaman = create_pengajuan_pinjaman(
                    pen_pin[0], pen_pin[1], pen_pin[2], pen_pin[3], pen_pin[4], pen_pin[5],
                    pen_pin[6], pen_pin[7], pen_pin[8], pen_pin[9], pen_pin[10], pen_pin[11],
                    pen_pin[12], pen_pin[13], pen_pin[14], pen_pin[15], pen_pin[16], pen_pin[17],
                    pen_pin[18], pen_pin[19], pen_pin[20], pen_pin[21], pen_pin[22], pen_pin[23],
                    pen_pin[24], pen_pin[25], pen_pin[26], pen_pin[27]
                )
                pengajuan_pinjaman_list.append(pengajuan_pinjaman)
            chunked_pengajuan_pinjaman = list(chunks(pengajuan_pinjaman_list, max_num))
            chunk_index = 0
            for chunk in chunked_pengajuan_pinjaman:
                chunk_index += 1
                try:
                    make_api_call_ojk(table_name, chunk, chunk_index)
                    self.stdout.write(self.style.SUCCESS(
                        "Completed API call for %s count: %s total: %s" % (
                            table_name, len(chunk), total)))
                except Exception as e:
                    sentry_client.captureException()
                    self.stdout.write(self.style.ERROR("Error in response for %s count: %s total: %s" % (
                        table_name, len(chunk), total)))
                    log_failures("data_%s" % table_name, total, chunk_index, chunk)

                total += increment

        ########################################################################
        increment = 10000
        total = 0
        table_name = 'pengajuan_pemberian_pinjaman'

        while total < 500000:  # TODO: refactor to get total based on query's count
            with connection.cursor() as cursor:
                cursor.execute(pengajuan_pemberian_pinjaman_query(increment, total, start_date, end_date))
                pengajuan_pemberian_pinjaman_data = cursor.fetchall()

            if len(pengajuan_pemberian_pinjaman_data) == 0:
                self.stdout.write(self.style.WARNING(
                    "No more data for %s total: %s" % (table_name, total)
                ))
                break

            pengajuan_pemberian_pinjaman_list = []
            for pen_pem in pengajuan_pemberian_pinjaman_data:
                pengajuan_pemberian_pinjaman = create_pengajuan_pemberian_pinjaman(
                    pen_pem[0], pen_pem[1], pen_pem[2], pen_pem[3], pen_pem[4], pen_pem[5],
                    pen_pem[6], pen_pem[7], pen_pem[8], pen_pem[9],
                )
                pengajuan_pemberian_pinjaman_list.append(pengajuan_pemberian_pinjaman)
            chunked_pengajuan_pemberian_pinjaman = list(chunks(pengajuan_pemberian_pinjaman_list, max_num))
            chunk_index = 0
            for chunk in chunked_pengajuan_pemberian_pinjaman:
                chunk_index += 1
                try:
                    make_api_call_ojk(table_name, chunk, chunk_index)
                    self.stdout.write(self.style.SUCCESS(
                        "Completed API call for %s count: %s total: %s" % (
                            table_name, len(chunk), total)))
                except Exception as e:
                    sentry_client.captureException()
                    self.stdout.write(self.style.ERROR("Error in response for %s count: %s total: %s" % (
                        table_name, len(chunk), total)))
                    log_failures("data_%s" % table_name, total, chunk_index, chunk)
            total += increment

        ########################################################################
        increment = 10000
        total = 0
        table_name = 'transaksi_pinjam_meminjam'

        while total < 500000:  # TODO: refactor to get total based on query's count
            with connection.cursor() as cursor:
                cursor.execute(transaksi_pinjam_meminjam_query(increment, total, start_date, end_date))
                transaksi_pinjam_meminjam_data = cursor.fetchall()

            if len(transaksi_pinjam_meminjam_data) == 0:
                self.stdout.write(self.style.WARNING(
                    "No more data for %s total: %s" % (table_name, total)
                ))
                break

            transaksi_pinjam_meminjam_list = []
            for tra_pin in transaksi_pinjam_meminjam_data:
                transaksi_pinjam_meminjam = create_transaksi_pinjam_meminjam(
                    tra_pin[0], tra_pin[1], tra_pin[2], tra_pin[3], tra_pin[4], tra_pin[5],
                    tra_pin[6], tra_pin[7], tra_pin[8], tra_pin[9], tra_pin[10], tra_pin[11],
                    tra_pin[12], tra_pin[13], tra_pin[14], tra_pin[15], tra_pin[16], tra_pin[17],
                    tra_pin[18], tra_pin[19], tra_pin[20]
                )
                transaksi_pinjam_meminjam_list.append(transaksi_pinjam_meminjam)
            chunked_transaksi_pinjam_meminjam = list(chunks(transaksi_pinjam_meminjam_list, max_num))
            chunk_index = 0
            for chunk in chunked_transaksi_pinjam_meminjam:
                chunk_index += 1
                try:
                    make_api_call_ojk(table_name, chunk, chunk_index)
                    self.stdout.write(self.style.SUCCESS(
                        "Completed API call for %s count: %s total: %s" % (
                            table_name, len(chunk), total)))
                except Exception as e:
                    sentry_client.captureException()
                    self.stdout.write(self.style.ERROR("Error in response for %s count: %s total: %s" % (
                        table_name, len(chunk), total)))
                    log_failures("data_%s" % table_name, total, chunk_index, chunk)
            total += increment
        ########################################################################
        increment = 10000
        total = 0
        table_name = 'pembayaran_pinjaman'

        while total < 1400000:  # TODO: refactor to get total based on query's count
            with connection.cursor() as cursor:
                cursor.execute(pembayaran_pinjaman_query(increment, total, start_date, end_date))
                pembayaran_pinjaman_data = cursor.fetchall()

            if len(pembayaran_pinjaman_data) == 0:
                self.stdout.write(self.style.WARNING(
                    "No more data for %s total: %s" % (table_name, total)
                ))
                break

            pembayaran_pinjaman_list = []
            for pem_pin in pembayaran_pinjaman_data:
                pembayaran_pinjaman = create_pembayaran_pinjaman(
                    pem_pin[0], pem_pin[1], pem_pin[2], pem_pin[3], pem_pin[4],
                    pem_pin[5], pem_pin[6], pem_pin[7], pem_pin[8], pem_pin[9],
                    pem_pin[10], pem_pin[11], pem_pin[12], pem_pin[13], pem_pin[14],
                    pem_pin[15]
                )
                pembayaran_pinjaman_list.append(pembayaran_pinjaman)
            chunked_pembayaran_pinjaman = list(chunks(pembayaran_pinjaman_list, max_num))
            chunk_index = 0
            for chunk in chunked_pembayaran_pinjaman:
                chunk_index += 1
                try:
                    make_api_call_ojk(table_name, chunk, chunk_index)
                    self.stdout.write(self.style.SUCCESS(
                        "Completed API call for %s count: %s total: %s" % (
                            table_name, len(chunk), total)))
                except Exception as e:
                    sentry_client.captureException()
                    self.stdout.write(self.style.ERROR("Error in response for %s count: %s total: %s" % (
                        table_name, len(chunk), total)))
                    log_failures("data_%s" % table_name, total, chunk_index, chunk)
            total += increment

        self.stdout.write(self.style.SUCCESS("======success===="))
