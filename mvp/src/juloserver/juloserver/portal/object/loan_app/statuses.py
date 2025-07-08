from builtins import object
import logging

from collections import namedtuple
from .constants import AppCheckType
from juloserver.julo.product_lines import ProductLineCodes as PLC


logger = logging.getLogger(__name__)


CheckItem = namedtuple('CheckItem', ['automation', 'prioritize', 'sequence',
        'data_to_check', 'description', 'check_type', 'app_field_id', 'strict_check'])

Checker = [

    ############################################################################
    # Application Checker
    ############################################################################

    CheckItem(
        automation     = 1,
        prioritize     = 1,
        sequence       = 1,
        data_to_check  = 'Umur 21-50',
        description    = 'Umur diantara 21 dan 50',
        check_type     = AppCheckType.BINARY,
        app_field_id   = 11, #dob
        strict_check   = {PLC.MTL1: True, PLC.MTL2: True,
                          PLC.STL1: True, PLC.STL2: True}
    ),
    CheckItem(
        automation     = 1,
        prioritize     = 1,
        sequence       = 2,
        data_to_check  = 'HP',
        description    = 'Milik sendiri',
        check_type     = AppCheckType.BINARY,
        app_field_id   = 9, #is_own_phone
        strict_check   = {PLC.MTL1: True, PLC.MTL2: True,
                          PLC.STL1: True, PLC.STL2: True}
    ), 
    CheckItem(
        automation     = 2,
        prioritize     = 1,
        sequence       = 3,
        data_to_check  = 'Self - NIK ',
        description    = 'Formulir vs. KPU',
        check_type     = AppCheckType.BINARY,
        app_field_id   = 13, #ktp
        strict_check   = {PLC.MTL1: False, PLC.MTL2: False,
                          PLC.STL1: False, PLC.STL2: False}
    ), 
    CheckItem(
        automation     = 1,
        prioritize     = 1,
        sequence       = 4,
        data_to_check  = 'Self - NIK',
        description    = 'Formulir vs. Kode Wilayah',
        check_type     = AppCheckType.BINARY,
        app_field_id   = 13, #ktp
        strict_check   = {PLC.MTL1: False, PLC.MTL2: False,
                          PLC.STL1: False, PLC.STL2: False}
    ), 
    CheckItem(
        automation     = 1,
        prioritize     = 1,
        sequence       = 5,
        data_to_check  = 'Self - NIK',
        description    = 'Formulir vs. DOB',
        check_type     = AppCheckType.BINARY,
        app_field_id   = 13, #ktp
        strict_check   = {PLC.MTL1: False, PLC.MTL2: False,
                          PLC.STL1: False, PLC.STL2: False}
    ), 
    CheckItem(
        automation     = 2,
        prioritize     = 1,
        sequence       = 6,
        data_to_check  = 'KTP',
        description    = 'Tidak kadaluarsa',
        check_type     = AppCheckType.BINARY,
        app_field_id   = 13, #ktp
        strict_check   = {PLC.MTL1: False, PLC.MTL2: False,
                          PLC.STL1: False, PLC.STL2: False}
    ), 
    CheckItem(
        automation     = 1,
        prioritize     = 1,
        sequence       = 7,
        data_to_check  = 'THP',
        description    = '> Rp 3.000.000/bulan',
        check_type     = AppCheckType.BINARY,
        app_field_id   = 50, #monthly_income
        strict_check   = {PLC.MTL1: True, PLC.MTL2: True,
                          PLC.STL1: True, PLC.STL2: True}
    ), 
    CheckItem(
        automation     = 0,
        prioritize     = 1,
        sequence       = 8,
        data_to_check  = 'Bank account atas nama sendiri',
        description    = '',
        check_type     = AppCheckType.BINARY,
        app_field_id   = None,
        strict_check   = {PLC.MTL1: False, PLC.MTL2: False,
                          PLC.STL1: False, PLC.STL2: False}
    ), 
    CheckItem(
        automation     = 0,
        prioritize     = 1,
        sequence       = 9,
        data_to_check  = 'Berdomisili di Jabodetabek',
        description    = '',
        check_type     = AppCheckType.BINARY,
        app_field_id   = None,
        strict_check   = {PLC.MTL1: False, PLC.MTL2: False,
                          PLC.STL1: False, PLC.STL2: False}
    ), 
    CheckItem(
        automation     = 0,
        prioritize     = 1,
        sequence       = 10,
        data_to_check  = 'SD (Scraped Data)',
        description    = 'SMS > 3 bulan',
        check_type     = AppCheckType.BINARY,
        app_field_id   = None,
        strict_check   = {PLC.MTL1: False, PLC.MTL2: False,
                          PLC.STL1: False, PLC.STL2: False}
    ), 
    CheckItem(
        automation     = 0,
        prioritize     = 1,
        sequence       = 11,
        data_to_check  = 'Not found in Blacklist Chinatrust Bank',
        description    = '',
        check_type     = AppCheckType.BINARY,
        app_field_id   = None,
        strict_check   = {PLC.MTL1: False, PLC.MTL2: False,
                          PLC.STL1: False, PLC.STL2: False}
    ), 
    CheckItem(
        automation     = 1,
        prioritize     = 1,
        sequence       = 12,
        data_to_check  = 'Spouse - Nama & DOB',
        description    = 'Suami/ istri tidak pernah ditolak JULO (suami ditolak, istri ditolak)',
        check_type     = AppCheckType.BINARY,
        app_field_id   = 33, #spouse_name
        strict_check   = {PLC.MTL1: False, PLC.MTL2: False,
                          PLC.STL1: False, PLC.STL2: False}
    ), 
    CheckItem(
        automation     = 1,
        prioritize     = 1,
        sequence       = 13,
        data_to_check  = 'Kerabat - Nama & DOB',
        description    = 'Kerabat tidak pernah ditolak JULO (kerabat ditolak, applicant ditolak)',
        check_type     = AppCheckType.BINARY,
        app_field_id   = 37,#kin_name
        strict_check   = {PLC.MTL1: False, PLC.MTL2: False,
                          PLC.STL1: False, PLC.STL2: False}
    ), 
    CheckItem(
        automation     = 0,
        prioritize     = 1,
        sequence       = 14,
        data_to_check  = 'Pekerjaan yang ditolak',
        description    = 'pengacara, wartawan, tni / security, freelance, wiraswasta, kolektor, ibu RT',
        check_type     = AppCheckType.BINARY,
        app_field_id   = None,
        strict_check   = {PLC.MTL1: False, PLC.MTL2: False,
                          PLC.STL1: False, PLC.STL2: False}
    ), 
    CheckItem(
        automation     = 1,
        prioritize     = 1,
        sequence       = 15,
        data_to_check  = 'Nama Perusahaan',
        description    = 'Formulir vs. PDF Blacklist PT',
        check_type     = AppCheckType.BINARY,
        app_field_id   = 46, #company_name
        strict_check   = {PLC.MTL1: False, PLC.MTL2: False,
                          PLC.STL1: False, PLC.STL2: False}
    ), 
    CheckItem(
        automation     = 1,
        prioritize     = 1,
        sequence       = 16,
        data_to_check  = 'Sudah bekerja > 3 bln di perusahana tsb',
        description    = '',
        check_type     = AppCheckType.BINARY,
        app_field_id   = 49, #job_start
        strict_check   = {PLC.MTL1: False, PLC.MTL2: False,
                          PLC.STL1: False, PLC.STL2: False}
    ), 
    CheckItem(
        automation     = 0,
        prioritize     = 1,
        sequence       = 17,
        data_to_check  = 'Tujuan pinjaman tidak di-blacklist',
        description    = '',
        check_type     = AppCheckType.BINARY,
        app_field_id   = None,
        strict_check   = {PLC.MTL1: False, PLC.MTL2: False,
                          PLC.STL1: False, PLC.STL2: False}
    ), 
    CheckItem(
        automation     = 0,
        prioritize     = 1,
        sequence       = 18,
        data_to_check  = 'SD Keyword',
        description    = 'mencari pinjaman',
        check_type     = AppCheckType.CURRENCY,
        app_field_id   = None,
        strict_check   = {PLC.MTL1: False, PLC.MTL2: False,
                          PLC.STL1: False, PLC.STL2: False}
    ), 
    CheckItem(
        automation     = 0,
        prioritize     = 1,
        sequence       = 19,
        data_to_check  = 'SD Keyword',
        description    = 'mengajukan/ pengajuan',
        check_type     = AppCheckType.CURRENCY,
        app_field_id   = None,
        strict_check   = {PLC.MTL1: False, PLC.MTL2: False,
                          PLC.STL1: False, PLC.STL2: False}
    ), 
    CheckItem(
        automation     = 0,
        prioritize     = 1,
        sequence       = 20,
        data_to_check  = 'SD Keyword',
        description    = 'ditolak',
        check_type     = AppCheckType.CURRENCY,
        app_field_id   = None,
        strict_check   = {PLC.MTL1: False, PLC.MTL2: False,
                          PLC.STL1: False, PLC.STL2: False}
    ), 
    CheckItem(
        automation     = 0,
        prioritize     = 1,
        sequence       = 21,
        data_to_check  = 'SD Keyword',
        description    = 'diterima',
        check_type     = AppCheckType.CURRENCY,
        app_field_id   = None,
        strict_check   = {PLC.MTL1: False, PLC.MTL2: False,
                          PLC.STL1: False, PLC.STL2: False}
    ), 
    CheckItem(
        automation     = 0,
        prioritize     = 1,
        sequence       = 22,
        data_to_check  = 'SD Keyword',
        description    = 'terlambat',
        check_type     = AppCheckType.CURRENCY,
        app_field_id   = None,
        strict_check   = {PLC.MTL1: False, PLC.MTL2: False,
                          PLC.STL1: False, PLC.STL2: False}
    ), 
    CheckItem(
        automation     = 0,
        prioritize     = 1,
        sequence       = 23,
        data_to_check  = 'SD Keyword',
        description    = 'bayar tepat waktu',
        check_type     = AppCheckType.CURRENCY,
        app_field_id   = None,
        strict_check   = {PLC.MTL1: False, PLC.MTL2: False,
                          PLC.STL1: False, PLC.STL2: False}
    ), 
    CheckItem(
        automation     = 0,
        prioritize     = 1,
        sequence       = 24,
        data_to_check  = 'SD Keyword',
        description    = 'kejujuran',
        check_type     = AppCheckType.CURRENCY,
        app_field_id   = None,
        strict_check   = {PLC.MTL1: False, PLC.MTL2: False,
                          PLC.STL1: False, PLC.STL2: False}
    ), 
    CheckItem(
        automation     = 0,
        prioritize     = 1,
        sequence       = 25,
        data_to_check  = 'SD Keyword',
        description    = 'kesopanan',
        check_type     = AppCheckType.CURRENCY,
        app_field_id   = None,
        strict_check   = {PLC.MTL1: False, PLC.MTL2: False,
                          PLC.STL1: False, PLC.STL2: False}
    ), 
    CheckItem(
        automation     = 0,
        prioritize     = 1,
        sequence       = 26,
        data_to_check  = 'Self - Phone No.',
        description    = 'ditemukan duplikat',
        check_type     = AppCheckType.BINARY,
        app_field_id   = None,
        strict_check   = {PLC.MTL1: False, PLC.MTL2: False,
                          PLC.STL1: False, PLC.STL2: False}
    ), 
    CheckItem(
        automation     = 0,
        prioritize     = 1,
        sequence       = 27,
        data_to_check  = 'Spouse - Phone No.',
        description    = 'ditemukan duplikat',
        check_type     = AppCheckType.BINARY,
        app_field_id   = None,
        strict_check   = {PLC.MTL1: False, PLC.MTL2: False,
                          PLC.STL1: False, PLC.STL2: False}
    ), 
    CheckItem(
        automation     = 0,
        prioritize     = 1,
        sequence       = 28,
        data_to_check  = 'Kerabat - Phone No.',
        description    = 'ditemukan duplikat',
        check_type     = AppCheckType.BINARY,
        app_field_id   = None,
        strict_check   = {PLC.MTL1: False, PLC.MTL2: False,
                          PLC.STL1: False, PLC.STL2: False}
    ), 
    CheckItem(
        automation     = 0,
        prioritize     = 1,
        sequence       = 29,
        data_to_check  = 'Kantor - Phone No.',
        description    = 'ditemukan duplikat',
        check_type     = AppCheckType.BINARY,
        app_field_id   = None,
        strict_check   = {PLC.MTL1: False, PLC.MTL2: False,
                          PLC.STL1: False, PLC.STL2: False}
    ), 
    CheckItem(
        automation     = 0,
        prioritize     = 1,
        sequence       = 30,
        data_to_check  = 'Self - Nama',
        description    = 'ditemukan duplikat',
        check_type     = AppCheckType.BINARY,
        app_field_id   = None,
        strict_check   = {PLC.MTL1: False, PLC.MTL2: False,
                          PLC.STL1: False, PLC.STL2: False}
    ), 
    CheckItem(
        automation     = 0,
        prioritize     = 1,
        sequence       = 31,
        data_to_check  = 'Spouse - Nama',
        description    = 'ditemukan duplikat',
        check_type     = AppCheckType.BINARY,
        app_field_id   = None,
        strict_check   = {PLC.MTL1: False, PLC.MTL2: False,
                          PLC.STL1: False, PLC.STL2: False}
    ), 
    CheckItem(
        automation     = 0,
        prioritize     = 1,
        sequence       = 32,
        data_to_check  = 'Kerabat - Nama',
        description    = 'ditemukan duplikat',
        check_type     = AppCheckType.BINARY,
        app_field_id   = None,
        strict_check   = {PLC.MTL1: False, PLC.MTL2: False,
                          PLC.STL1: False, PLC.STL2: False}
    ), 
    CheckItem(
        automation     = 0,
        prioritize     = 1,
        sequence       = 33,
        data_to_check  = 'Kantor - Nama',
        description    = 'ditemukan duplikat',
        check_type     = AppCheckType.BINARY,
        app_field_id   = None,
        strict_check   = {PLC.MTL1: False, PLC.MTL2: False,
                          PLC.STL1: False, PLC.STL2: False}
    ), 
    CheckItem(
        automation     = 0,
        prioritize     = 1,
        sequence       = 34,
        data_to_check  = 'Self - NIK',
        description    = 'Formulir vs. Foto KTP',
        check_type     = AppCheckType.BINARY,
        app_field_id   = None,
        strict_check   = {PLC.MTL1: False, PLC.MTL2: False,
                          PLC.STL1: False, PLC.STL2: False}
    ), 
    CheckItem(
        automation     = 0,
        prioritize     = 1,
        sequence       = 35,
        data_to_check  = 'Self - Nama ',
        description    = 'Formulir vs. Foto KTP',
        check_type     = AppCheckType.BINARY,
        app_field_id   = None,
        strict_check   = {PLC.MTL1: False, PLC.MTL2: False,
                          PLC.STL1: False, PLC.STL2: False}
    ), 
    CheckItem(
        automation     = 0,
        prioritize     = 1,
        sequence       = 36,
        data_to_check  = 'Self - DOB',
        description    = 'Formulir vs. Foto KTP',
        check_type     = AppCheckType.BINARY,
        app_field_id   = None,
        strict_check   = {PLC.MTL1: False, PLC.MTL2: False,
                          PLC.STL1: False, PLC.STL2: False}
    ), 
    CheckItem(
        automation     = 0,
        prioritize     = 1,
        sequence       = 37,
        data_to_check  = 'Self - Kelamin',
        description    = 'Formulir vs. Foto KTP',
        check_type     = AppCheckType.BINARY,
        app_field_id   = None,
        strict_check   = {PLC.MTL1: False, PLC.MTL2: False,
                          PLC.STL1: False, PLC.STL2: False}
    ),
        CheckItem(
        automation     = 0,
        prioritize     = 1,
        sequence       = 38,
        data_to_check  = 'Self - NIK',
        description    = 'Formulir vs. Foto KK',
        check_type     = AppCheckType.BINARY,
        app_field_id   = None,
        strict_check   = {PLC.MTL1: False, PLC.MTL2: False,
                          PLC.STL1: False, PLC.STL2: False}
    ), 
    CheckItem(
        automation     = 0,
        prioritize     = 1,
        sequence       = 39,
        data_to_check  = 'Self - Nama',
        description    = 'Formulir vs. Foto KK',
        check_type     = AppCheckType.BINARY,
        app_field_id   = None,
        strict_check   = {PLC.MTL1: False, PLC.MTL2: False,
                          PLC.STL1: False, PLC.STL2: False}
    ), 
    CheckItem(
        automation     = 0,
        prioritize     = 1,
        sequence       = 40,
        data_to_check  = 'Self - DOB',
        description    = 'Formulir vs. Foto KK',
        check_type     = AppCheckType.BINARY,
        app_field_id   = None,
        strict_check   = {PLC.MTL1: False, PLC.MTL2: False,
                          PLC.STL1: False, PLC.STL2: False}
    ), 
    CheckItem(
        automation     = 0,
        prioritize     = 1,
        sequence       = 41,
        data_to_check  = 'Self - Gender/Kelamin',
        description    = 'Formulir vs. Foto KK',
        check_type     = AppCheckType.BINARY,
        app_field_id   = None,
        strict_check   = {PLC.MTL1: False, PLC.MTL2: False,
                          PLC.STL1: False, PLC.STL2: False}
    ), 
    CheckItem(
        automation     = 0,
        prioritize     = 1,
        sequence       = 42,
        data_to_check  = 'Status perkawinan ',
        description    = 'Formulir vs. Foto KTP',
        check_type     = AppCheckType.BINARY,
        app_field_id   = None,
        strict_check   = {PLC.MTL1: False, PLC.MTL2: False,
                          PLC.STL1: False, PLC.STL2: False}
    ), 
    CheckItem(
        automation     = 0,
        prioritize     = 1,
        sequence       = 43,
        data_to_check  = 'Status perkawinan ',
        description    = 'Formulir vs. Foto KK',
        check_type     = AppCheckType.BINARY,
        app_field_id   = None,
        strict_check   = {PLC.MTL1: False, PLC.MTL2: False,
                          PLC.STL1: False, PLC.STL2: False}
    ), 
    CheckItem(
        automation     = 0,
        prioritize     = 1,
        sequence       = 44,
        data_to_check  = 'Spouse - KTP Expired',
        description    = 'Foto KTP',
        check_type     = AppCheckType.BINARY,
        app_field_id   = None,
        strict_check   = {PLC.MTL1: False, PLC.MTL2: False,
                          PLC.STL1: False, PLC.STL2: False}
    ), 
    CheckItem(
        automation     = 0,
        prioritize     = 1,
        sequence       = 45,
        data_to_check  = 'Spouse - NIK',
        description    = 'KTP vs. KPU',
        check_type     = AppCheckType.BINARY,
        app_field_id   = None,
        strict_check   = {PLC.MTL1: False, PLC.MTL2: False,
                          PLC.STL1: False, PLC.STL2: False}
    ), 
    CheckItem(
        automation     = 0,
        prioritize     = 1,
        sequence       = 46,
        data_to_check  = 'Spouse - Nama ',
        description    = 'Formulir vs. Foto KTP',
        check_type     = AppCheckType.BINARY,
        app_field_id   = None,
        strict_check   = {PLC.MTL1: False, PLC.MTL2: False,
                          PLC.STL1: False, PLC.STL2: False}
    ), 
    CheckItem(
        automation     = 0,
        prioritize     = 1,
        sequence       = 47,
        data_to_check  = 'Spouse - DOB',
        description    = 'Formulir vs. Foto KTP',
        check_type     = AppCheckType.BINARY,
        app_field_id   = None,
        strict_check   = {PLC.MTL1: False, PLC.MTL2: False,
                          PLC.STL1: False, PLC.STL2: False}
    ), 
    CheckItem(
        automation     = 0,
        prioritize     = 1,
        sequence       = 48,
        data_to_check  = 'Spouse - Gender / Kelamin',
        description    = 'Formulir vs. Foto KTP',
        check_type     = AppCheckType.BINARY,
        app_field_id   = None,
        strict_check   = {PLC.MTL1: False, PLC.MTL2: False,
                          PLC.STL1: False, PLC.STL2: False}
    ), 
    CheckItem(
        automation     = 0,
        prioritize     = 1,
        sequence       = 49,
        data_to_check  = 'Spouse - NIK',
        description    = 'Foto KTP vs. Foto KK',
        check_type     = AppCheckType.BINARY,
        app_field_id   = None,
        strict_check   = {PLC.MTL1: False, PLC.MTL2: False,
                          PLC.STL1: False, PLC.STL2: False}
    ), 
    CheckItem(
        automation     = 0,
        prioritize     = 1,
        sequence       = 50,
        data_to_check  = 'Spouse - Nama',
        description    = 'Formulir vs. Foto KK',
        check_type     = AppCheckType.BINARY,
        app_field_id   = None,
        strict_check   = {PLC.MTL1: False, PLC.MTL2: False,
                          PLC.STL1: False, PLC.STL2: False}
    ), 
    CheckItem(
        automation     = 0,
        prioritize     = 1,
        sequence       = 51,
        data_to_check  = 'Spouse - DOB ',
        description    = 'Formulir vs. Foto KK',
        check_type     = AppCheckType.BINARY,
        app_field_id   = None,
        strict_check   = {PLC.MTL1: False, PLC.MTL2: False,
                          PLC.STL1: False, PLC.STL2: False}
    ), 
    CheckItem(
        automation     = 0,
        prioritize     = 1,
        sequence       = 52,
        data_to_check  = 'Spouse - Kelamin ',
        description    = 'Formulir vs. Foto KK',
        check_type     = AppCheckType.BINARY,
        app_field_id   = None,
        strict_check   = {PLC.MTL1: False, PLC.MTL2: False,
                          PLC.STL1: False, PLC.STL2: False}
    ), 
    CheckItem(
        automation     = 0,
        prioritize     = 1,
        sequence       = 53,
        data_to_check  = 'Tanggungan',
        description    = 'Formulir vs. Foto KK',
        check_type     = AppCheckType.CURRENCY,
        app_field_id   = None,
        strict_check   = {PLC.MTL1: False, PLC.MTL2: False,
                          PLC.STL1: False, PLC.STL2: False}
    ), 
    CheckItem(
        automation     = 0,
        prioritize     = 1,
        sequence       = 54,
        data_to_check  = 'Domisili - Nama',
        description    = 'Formulir vs. Doc (tergantung status kepemilikan domisili self/ ortu/ pemilik kos/kontrak)',
        check_type     = AppCheckType.BINARY,
        app_field_id   = None,
        strict_check   = {PLC.MTL1: False, PLC.MTL2: False,
                          PLC.STL1: False, PLC.STL2: False}
    ), 
    CheckItem(
        automation     = 0,
        prioritize     = 1,
        sequence       = 55,
        data_to_check  = 'Domisili - Alamat',
        description    = 'Formulir vs. Doc',
        check_type     = AppCheckType.BINARY,
        app_field_id   = None,
        strict_check   = {PLC.MTL1: False, PLC.MTL2: False,
                          PLC.STL1: False, PLC.STL2: False}
    ), 
    CheckItem(
        automation     = 0,
        prioritize     = 1,
        sequence       = 56,
        data_to_check  = 'Domisili - Alamat',
        description    = 'Formulir vs. GPS (alamat rumah)',
        check_type     = AppCheckType.OPTIONS,
        app_field_id   = None,
        strict_check   = {PLC.MTL1: False, PLC.MTL2: False,
                          PLC.STL1: False, PLC.STL2: False}
    ), 
    CheckItem(
        automation     = 0,
        prioritize     = 1,
        sequence       = 57,
        data_to_check  = 'Domisili - Alamat',
        description    = 'Formulir vs. GPS (kodepos kantor)',
        check_type     = AppCheckType.OPTIONS,
        app_field_id   = None,
        strict_check   = {PLC.MTL1: False, PLC.MTL2: False,
                          PLC.STL1: False, PLC.STL2: False}
    ), 
    CheckItem(
        automation     = 0,
        prioritize     = 1,
        sequence       = 58,
        data_to_check  = 'Gaji - Nama',
        description    = 'Formulir vs. Doc',
        check_type     = AppCheckType.BINARY,
        app_field_id   = None,
        strict_check   = {PLC.MTL1: False, PLC.MTL2: False,
                          PLC.STL1: False, PLC.STL2: False}
    ), 
    CheckItem(
        automation     = 0,
        prioritize     = 1,
        sequence       = 59,
        data_to_check  = 'Gaji - Jumlah THP > Rp 3 jt',
        description    = 'Formulir vs. Doc',
        check_type     = AppCheckType.CURRENCY,
        app_field_id   = None,
        strict_check   = {PLC.MTL1: False, PLC.MTL2: False,
                          PLC.STL1: False, PLC.STL2: False}
    ), 
    CheckItem(
        automation     = 0,
        prioritize     = 1,
        sequence       = 60,
        data_to_check  = 'Penghasilan Lainnya - Nama',
        description    = 'Formulir vs. Doc',
        check_type     = AppCheckType.BINARY,
        app_field_id   = None,
        strict_check   = {PLC.MTL1: False, PLC.MTL2: False,
                          PLC.STL1: False, PLC.STL2: False}
    ), 
    CheckItem(
        automation     = 0,
        prioritize     = 1,
        sequence       = 61,
        data_to_check  = 'Penghasilan Lainnya - Jumlah',
        description    = 'Formulir vs. Doc',
        check_type     = AppCheckType.CURRENCY,
        app_field_id   = None,
        strict_check   = {PLC.MTL1: False, PLC.MTL2: False,
                          PLC.STL1: False, PLC.STL2: False}
    ), 
    CheckItem(
        automation     = 0,
        prioritize     = 1,
        sequence       = 62,
        data_to_check  = 'Biaya sewa/ cicilan rumah per bln',
        description    = 'Formulir',
        check_type     = AppCheckType.CURRENCY,
        app_field_id   = None,
        strict_check   = {PLC.MTL1: False, PLC.MTL2: False,
                          PLC.STL1: False, PLC.STL2: False}
    ), 
    CheckItem(
        automation     = 0,
        prioritize     = 1,
        sequence       = 63,
        data_to_check  = 'Total pengeluaran per bln (selain rumah) ',
        description    = 'Formulir',
        check_type     = AppCheckType.CURRENCY,
        app_field_id   = None,
        strict_check   = {PLC.MTL1: False, PLC.MTL2: False,
                          PLC.STL1: False, PLC.STL2: False}
    ), 
    CheckItem(
        automation     = 0,
        prioritize     = 1,
        sequence       = 64,
        data_to_check  = 'Total cicilan hutang per bln',
        description    = 'Formulir vs. SD vs. Email customer',
        check_type     = AppCheckType.CURRENCY,
        app_field_id   = None,
        strict_check   = {PLC.MTL1: False, PLC.MTL2: False,
                          PLC.STL1: False, PLC.STL2: False}
    ), 
    CheckItem(
        automation     = 0,
        prioritize     = 1,
        sequence       = 65,
        data_to_check  = 'Selfie',
        description    = 'Doc vs. KTP',
        check_type     = AppCheckType.BINARY,
        app_field_id   = None,
        strict_check   = {PLC.MTL1: False, PLC.MTL2: False,
                          PLC.STL1: False, PLC.STL2: False}
    ), 
    CheckItem(
        automation     = 0,
        prioritize     = 1,
        sequence       = 66,
        data_to_check  = 'FB - DOB ',
        description    = 'Formulir vs. FB',
        check_type     = AppCheckType.BINARY,
        app_field_id   = None,
        strict_check   = {PLC.MTL1: False, PLC.MTL2: False,
                          PLC.STL1: False, PLC.STL2: False}
    ), 
    CheckItem(
        automation     = 0,
        prioritize     = 1,
        sequence       = 67,
        data_to_check  = 'FB - Gender/Kelamin',
        description    = 'Formulir vs. FB',
        check_type     = AppCheckType.BINARY,
        app_field_id   = None,
        strict_check   = {PLC.MTL1: False, PLC.MTL2: False,
                          PLC.STL1: False, PLC.STL2: False}
    ), 
    CheckItem(
        automation     = 0,
        prioritize     = 1,
        sequence       = 68,
        data_to_check  = 'Phone verification: Employer',
        description    = '',
        check_type     = AppCheckType.BINARY,
        app_field_id   = None,
        strict_check   = {PLC.MTL1: False, PLC.MTL2: False,
                          PLC.STL1: False, PLC.STL2: False}
    ),
    CheckItem(
        automation     = 0,
        prioritize     = 1,
        sequence       = 69,
        data_to_check  = 'Phone verification: Spouse',
        description    = '',
        check_type     = AppCheckType.BINARY,
        app_field_id   = None,
        strict_check   = {PLC.MTL1: False, PLC.MTL2: False,
                          PLC.STL1: False, PLC.STL2: False}
    ),
    CheckItem(
        automation     = 0,
        prioritize     = 1,
        sequence       = 70,
        data_to_check  = 'Phone verification: Kin',
        description    = '',
        check_type     = AppCheckType.BINARY,
        app_field_id   = None,
        strict_check   = {PLC.MTL1: False, PLC.MTL2: False,
                          PLC.STL1: False, PLC.STL2: False}
    ),
    CheckItem(
        automation     = 1,
        prioritize     = 1,
        sequence       = 71,
        data_to_check  = 'Pekerjaan',
        description    = 'Pekerjaan nasabah tidak di-blacklist',
        check_type     = AppCheckType.BINARY,
        app_field_id   = 42, #job_type
        strict_check   = {PLC.MTL1: True, PLC.MTL2: True,
                          PLC.STL1: True, PLC.STL2: True}
    ),
    CheckItem(
        automation     = 1,
        prioritize     = 1,
        sequence       = 72,
        data_to_check  = 'FB',
        description    = 'FB friends > 50',
        check_type     = AppCheckType.BINARY,
        app_field_id   = 82, #fb_friend_count
        strict_check   = {PLC.MTL1: False, PLC.MTL2: False,
                          PLC.STL1: False, PLC.STL2: False}
    ),
    CheckItem(
        automation     = 1,
        prioritize     = 1,
        sequence       = 73,
        data_to_check  = 'FB',
        description    = 'DOB nasabah di FB = DOB nasabah di formulir',
        check_type     = AppCheckType.BINARY,
        app_field_id   = 81, #fb_dob
        strict_check   = {PLC.MTL1: False, PLC.MTL2: False,
                          PLC.STL1: False, PLC.STL2: False}
    ),
    CheckItem(
        automation     = 1,
        prioritize     = 1,
        sequence       = 74,
        data_to_check  = 'FB',
        description    = 'Gender nasabah di FB = gender nasabah di formulir',
        check_type     = AppCheckType.BINARY,
        app_field_id   = 80, #fb_gender
        strict_check   = {PLC.MTL1: False, PLC.MTL2: False,
                          PLC.STL1: False, PLC.STL2: False}
    ),
    CheckItem(
        automation     = 1,
        prioritize     = 1,
        sequence       = 75,
        data_to_check  = 'FB',
        description    = 'Email nasabah di FB = email nasabah di formulir',
        check_type     = AppCheckType.BINARY,
        app_field_id   = 79, #fb_email
        strict_check   = {PLC.MTL1: False, PLC.MTL2: False,
                          PLC.STL1: False, PLC.STL2: False}
    ),
    CheckItem(
        automation     = 0,
        prioritize     = 1,
        sequence       = 76,
        data_to_check  = 'Domisili',
        description    = 'Jarak alamat rumah di Formulir ke alamat rumah di Konfirmasi GPS < 100 meter',
        check_type     = AppCheckType.BINARY,
        app_field_id   = None,
        strict_check   = {PLC.MTL1: False, PLC.MTL2: False,
                          PLC.STL1: False, PLC.STL2: False}
    ),
]

class CheckItemManager(object):

    @classmethod
    def get_or_none_bycode(cls, code):
        for status in Checker:
            if status.code == code:
                logger.debug({})
                return status
        logger.warn({})
        return None

    @classmethod
    def get_or_none_byfield(cls, field):
        for status in Checker:
            if status.field == field:
                logger.debug({})
                return status
        logger.warn({})
        return  None
