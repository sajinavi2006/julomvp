from builtins import str
from builtins import chr
from builtins import range
import base64
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.backends import default_backend
import json
from datetime import datetime
import requests

url = 'https://pusdafil.ojk.go.id/PusdafilAPI/pelaporanharian'

date = datetime.now()

BS = 16
pad = lambda s: s + (BS - len(s) % BS) * chr(BS - len(s) % BS)

reg_pengguna = {
    'id_penyelenggara':'810069','id_pengguna':'1000000000','jenis_pengguna':1,
    'tgl_registrasi':date.today().strftime("%Y-%m-%d"),'nama_pengguna':'RyanSaputra',
    'jenis_identitas':1,'no_identitas':'3371020411890002',
    'no_npwp':'1234567890','id_jenis_badan_hukum':1,'tempat_lahir':'SEMARANG',
    'tgl_lahir':date.today().strftime("%Y-%m-%d"),'id_jenis_kelamin':1,
    'alamat':'Jl.Rumah','id_kota':'e282','id_provinsi':36,'kode_pos':'11480',
    'id_agama':1,'id_status_perkawinan':1,'id_pekerjaan':1,'id_bidang_pekerjaan':'e2',
    'id_pekerjaan_online':1,'pendapatan':3,'pengalaman_kerja':1,'id_pendidikan':3,
    'nama_perwakilan':'tes_nama_perwakilan','no_identitas_perwakilan':'2345678901'
}

reg_lender = {
    'id_penyelenggara':'810069', 'id_pengguna':1000000000, 'id_lender':'1231312',
    'id_negara_domisili':0, 'id_kewarganegaraan':0, 'sumber_dana':'bank'
}

reg_borrower = {
    'id_penyelenggara':'810069','id_pengguna':1000000000,'id_borrower':'231456412',
    'total_aset':500000,'status_kepemilikan_rumah':3
}

pengajuan_pinjaman = {
    'id_penyelenggara':'810069', 'id_pinjaman':'3000000', 'id_borrower':'231456412',
    'id_syariah':1, 'id_status_pengajuan_pinjaman':1, 'nama_pinjaman':'Andreas',
    'tgl_pengajuan_pinjaman':date.today().strftime("%Y-%m-%d"),'nilai_permohonan_pinjaman':5000000,
    'jangka_waktu_pinjaman':3, 'satuan_jangka_waktu_pinjaman': 2, 'penggunaan_pinjaman':'e0',
    'agunan':2, 'jenis_agunan':8, 'rasio_pinjaman_nilai_agunan':0,
    'permintaan_jaminan':'Data permintaan jaminan','rasio_pinjaman_aset':1, 'cicilan_bulan':1,
    'rating_pengajuan_pinjaman':'Lancar','nilai_plafond':5000000, 'nilai_pengajuan_pinjaman':5000000,
    'suku_bunga_pinjaman':7,'satuan_suku_bunga_pinjaman':1, 'jenis_bunga':1,
    'tgl_mulai_publikasi_pinjaman':date.today().strftime("%Y-%m-%d"),'rencana_jangka_waktu_publikasi':1,
    'realisasi_jangka_waktu_publikasi':2,'tgl_mulai_pendanaan':date.today().strftime("%Y-%m-%d"),
    'frekuensi_pinjaman':3
}

pengajuan_pemberian_pinjaman = {
    'id_penyelenggara':'810069', 'id_pinjaman':'3000000', 'id_borrower':'231456412',
    'id_lender':'1231312', 'no_perjanjian_lender':'7000000',
    'tgl_perjanjian_lender':date.today().strftime("%Y-%m-%d"),
    'tgl_penawaran_pemberian_pinjaman':date.today().strftime("%Y-%m-%d"),
    'nilai_penawaran_pinjaman':8000000, 'nilai_penawaran_disetujui':80000000,
    'no_va_lender':'1781000002142'
}

transaksi_pinjam_meminjam = {
    'id_penyelenggara':'810069', 'id_pinjaman':'3000000', 'id_borrower':'231456412',
    'id_lender':'1231312', 'id_transaksi':87467, 'no_perjanjian_borrower':'6000000',
    'tgl_perjanjian_borrower':date.today().strftime("%Y-%m-%d"), 'nilai_pendanaan':8000000,
    'suku_bunga_pinjaman':7,'satuan_suku_bunga_pinjaman':3, 'id_jenis_pembayaran':1,
    'id_frekuensi_pembayaran':3,'nilai_angsuran':500000, 'objek_jaminan':'', 'jangka_waktu_pinjaman':1,
    'satuan_jangka_waktu_pinjaman':3, 'tgl_jatuh_tempo':date.today().strftime("%Y-%m-%d"),
    'tgl_pendanaan':date.today().strftime("%Y-%m-%d"),'tgl_penyaluran_dana':date.today().strftime("%Y-%m-%d"),
    'no_ea_transaksi':'5681000002142','frekuensi_pendanaan':2
}

pembayaran_pinjaman = {
    'id_penyelenggara':'810069', 'id_pinjaman':'3000000', 'id_borrower':'231456412',
    'id_lender':'1231312', 'id_transaksi':'87467', 'id_pembayaran':'5000000',
    'tgl_jatuh_tempo':date.today().strftime("%Y-%m-%d"),
    'tgl_jatuh_tempo_selanjutnya':date.today().strftime("%Y-%m-%d"),
    'tgl_pembayaran_borrower':date.today().strftime("%Y-%m-%d"),
    'tgl_pembayaran_penyelenggara':date.today().strftime("%Y-%m-%d"),'sisa_pinjaman_berjalan':1000000,
    'id_status_pinjaman':1,'tgl_pelunasan_borrower':date.today().strftime("%Y-%m-%d"),
    'tgl_pelunasan_penyelenggara':date.today().strftime("%Y-%m-%d"),'denda':0, 'nilai_pembayaran':5000000
}


def encrypt(raw):
    raw = pad(raw)
    key = b'4bd393e7a457f9023d9ba95fffb5a2e1'
    iv = b'ijzh84t1w9xa56s9'
    backend = default_backend()
    cipher = Cipher(algorithms.AES(key), modes.CBC(iv), backend)
    encryptor = cipher.encryptor()
    en = encryptor.update(raw.encode('utf8'))
    return base64.b64encode(base64.b64encode(en) + b'::'+ iv )


def update_reg_pengguna(reg_pengguna, i):
    reg_pengguna['id_pengguna'] = str(int(reg_pengguna['id_pengguna']) + i)
    return reg_pengguna


def update_reg_lender(reg_lender, i):
    reg_lender['id_pengguna'] = int(reg_lender['id_pengguna'])+i
    reg_lender['id_lender'] = str(int(reg_lender['id_lender']) + i)
    return reg_lender


def update_reg_borrower(reg_borrower, i):
    reg_borrower['id_pengguna'] = int(reg_borrower['id_pengguna']) + i
    reg_borrower['id_borrower'] = str(int(reg_borrower['id_borrower']) + i)
    return reg_borrower


def update_pengajuan_pinjaman(pengajuan_pinjaman, i):
    pengajuan_pinjaman['id_pinjaman'] = str(int(pengajuan_pinjaman['id_pinjaman']) + i)
    pengajuan_pinjaman['id_borrower'] = str(int(pengajuan_pinjaman['id_borrower']) + i)
    return pengajuan_pinjaman


def update_pengajuan_pemberian_pinjaman(
    pengajuan_pemberian_pinjaman, i):

    pengajuan_pemberian_pinjaman['id_pinjaman'] = str(int(pengajuan_pemberian_pinjaman['id_pinjaman']) + i)
    pengajuan_pemberian_pinjaman['id_borrower'] = str(int(pengajuan_pemberian_pinjaman['id_borrower']) + i)
    pengajuan_pemberian_pinjaman['id_lender'] = str(int(pengajuan_pemberian_pinjaman['id_lender']) + i)
    pengajuan_pemberian_pinjaman['no_perjanjian_lender'] = str(int(
        pengajuan_pemberian_pinjaman['no_perjanjian_lender']) + 1)
    pengajuan_pemberian_pinjaman['nilai_penawaran_pinjaman'] = pengajuan_pemberian_pinjaman[
        'nilai_penawaran_pinjaman'] + i
    pengajuan_pemberian_pinjaman['nilai_penawaran_disetujui'] = pengajuan_pemberian_pinjaman[
        'nilai_penawaran_disetujui'] + i
    pengajuan_pemberian_pinjaman['no_va_lender'] = str(int(pengajuan_pemberian_pinjaman['no_va_lender']) + i)
    return pengajuan_pemberian_pinjaman


def update_transaksi_pinjam_meminjam(
    transaksi_pinjam_meminjam, i):
    transaksi_pinjam_meminjam['id_pinjaman'] = str(int(transaksi_pinjam_meminjam['id_pinjaman']) +i )
    transaksi_pinjam_meminjam['id_borrower'] = str(int(transaksi_pinjam_meminjam['id_borrower']) + i)
    transaksi_pinjam_meminjam['id_lender'] = str(int(transaksi_pinjam_meminjam['id_lender']) + i)
    transaksi_pinjam_meminjam['id_transaksi'] = transaksi_pinjam_meminjam['id_transaksi'] + i
    transaksi_pinjam_meminjam['no_perjanjian_borrower'] = str(int(
        transaksi_pinjam_meminjam['no_perjanjian_borrower']) + i)
    transaksi_pinjam_meminjam['nilai_pendanaan'] = transaksi_pinjam_meminjam['nilai_pendanaan'] + i
    transaksi_pinjam_meminjam['no_ea_transaksi'] = str(int(transaksi_pinjam_meminjam['no_ea_transaksi']) + i)
    return transaksi_pinjam_meminjam


def update_pembayaran_pinjaman(
    pembayaran_pinjaman, i):
    pembayaran_pinjaman['id_pinjaman'] = str(int(pembayaran_pinjaman['id_pinjaman'])+i)
    pembayaran_pinjaman['id_borrower'] = str(int(pembayaran_pinjaman['id_borrower']) + i)
    pembayaran_pinjaman['id_lender'] = str(int(pembayaran_pinjaman['id_lender']) + i)
    pembayaran_pinjaman['id_transaksi'] = str(int(pembayaran_pinjaman['id_transaksi']) + i)
    pembayaran_pinjaman['id_pembayaran'] = str(int(pembayaran_pinjaman['id_pembayaran']) + i)
    return pembayaran_pinjaman


def call_pusdafil_api_for_ojk_license():

    try:
        reg_pengguna_data = []
        reg_lender_data = []
        reg_borrower_data = []
        pengajuan_pinjaman_data = []
        pengajuan_pemberian_pinjaman_data = []
        transaksi_pinjam_meminjam_data = []
        pembayaran_pinjaman_data = []
        for i in range(0, 100):

            # reg_pengguna update
            reg_pengguna_copy = reg_pengguna.copy()
            reg_pengguna_data.append(update_reg_pengguna(reg_pengguna_copy, i))

            # reg_lender update
            reg_lender_copy = reg_lender.copy()
            reg_lender_data.append(update_reg_lender(reg_lender_copy, i))

            # update_reg_borrower
            reg_borrower_copy = reg_borrower.copy()
            reg_borrower_data.append(update_reg_borrower(reg_borrower_copy, i))

            # update_pengajuan_pinjaman
            pengajuan_pinjaman_copy = pengajuan_pinjaman.copy()
            pengajuan_pinjaman_data.append(update_pengajuan_pinjaman(pengajuan_pinjaman_copy, i))

            # update_pengajuan_pemberian_pinjaman
            pengajuan_pemberian_pinjaman_copy = pengajuan_pemberian_pinjaman.copy()
            pengajuan_pemberian_pinjaman_data.append(update_pengajuan_pemberian_pinjaman(
                pengajuan_pemberian_pinjaman_copy, i))

            # update_transaksi_pinjam_meminjam
            transaksi_pinjam_meminjam_copy = transaksi_pinjam_meminjam.copy()
            transaksi_pinjam_meminjam_data.append(update_transaksi_pinjam_meminjam(
                transaksi_pinjam_meminjam_copy, i))

            #update_pembayaran_pinjaman
            pembayaran_pinjaman_copy = pembayaran_pinjaman.copy()
            pembayaran_pinjaman_data.append(
                update_pembayaran_pinjaman(pembayaran_pinjaman_copy, i))

        data = {}

        raw = json.dumps(reg_pengguna_data)
        data['reg_pengguna'] = encrypt(raw)

        raw = json.dumps(reg_lender_data)
        data['reg_lender'] = encrypt(raw)

        raw = json.dumps(reg_borrower_data)
        data['reg_borrower'] = encrypt(raw)

        raw = json.dumps(pengajuan_pinjaman_data)
        data['pengajuan_pinjaman'] = encrypt(raw)

        raw = json.dumps(pengajuan_pemberian_pinjaman_data)
        data['pengajuan_pemberian_pinjaman'] = encrypt(raw)

        raw = json.dumps(transaksi_pinjam_meminjam_data)
        data['transaksi_pinjam_meminjam'] = encrypt(raw)

        raw = json.dumps(pembayaran_pinjaman_data)
        data['pembayaran_pinjaman'] = encrypt(raw)

        response = requests.post(url, data, auth=('pusdafil@julo.co.id', '88Julo882020'))

        if response.json().get('request_status') != 200:
            return response

        return response

    except Exception as e:
        return e

response = call_pusdafil_api_for_ojk_license()
#print(response.json()) # uncomment these print to see the result
