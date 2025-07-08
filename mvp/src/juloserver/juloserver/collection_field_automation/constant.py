class VisitResultCodes(object):
    REFUSE_PAY = 'menolak bayar'
    VISIT_RESULT_MAPPING_LIST = [
        'PTP', 'titip pesan', REFUSE_PAY,
        'SKIP', 'visit ulang', 'alamat tidak valid'
    ]
    HOME = 'Rumah'
    OFFICE = 'Kantor'
    OTHER = 'Lainnya'
    VISIT_LOCATION_LIST = [
        HOME, OFFICE, OTHER
    ]
    REFUSE_PAY_REASONS = [
        'PHK/Bangkrut',
        'Sakit Kronis',
        'Bencana Alam',
        'Tidak Niat Bayar',
        'Ada Kebutuhan Mendesak',
        'Penurunan Penghasilan',
        'Banyak Pinjaman',
        'Positif Covid',
        'Nasabah Meninggal',
        'Lainnnya',
    ]
