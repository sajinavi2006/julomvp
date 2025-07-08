from builtins import object
from collections import namedtuple

MAXIMUM_PULSA_TRANSACTION_HISTORIES = 5
PREFIX_MOBILE_OPERATOR_LENGTH = 4


class FeatureNameConst(object):
    TRANSACTION_METHOD_HIGHLIGHT = 'ppob_v2_transaction_method_highlight'
    FORCE_CUSTOMER_TRAIN_TICKET = 'ppob_v2_force_customer_train_ticket'
    SEPULSA_AYOCONNECT_EWALLET_SWITCH = 'sepulsa_ayoconnect_ewallet_switch'
    SEPULSA_XFERS_EWALLET_SWITCH = 'sepulsa_xfers_ewallet_switch'


class SepulsaTransactionStatus:
    SUCCESS = 'success'
    FAILED = 'failed'
    PENDING = 'pending'
    INITIATE = 'initiate'


class SepulsaProductType(object):
    EWALLET = 'e-wallet'
    ELECTRICITY = 'electricity'
    BPJS = 'bpjs'
    MOBILE = 'mobile'
    TRAIN_TICKET = 'train_ticket'
    PDAM = 'pdam'
    INTERNET_BILL = 'internet_bill'
    E_WALLET_OPEN_PAYMENT = 'ewallet_open_payment'


class SepulsaProductCategory(object):
    POSTPAID = (
        'mobile_postpaid',
        'bpjs_kesehatan',
        'tagihan_listrik',
        'tagihan_air',
        'tiket_kereta',
    )
    PRE_PAID_AND_DATA = ('paket_data', 'pulsa')
    PULSA = 'pulsa'
    PAKET_DATA = 'paket_data'
    BPJS_KESEHATAN = ('bpjs_kesehatan',)
    ELECTRICITY_POSTPAID = 'tagihan_listrik'
    ELECTRICITY_PREPAID = 'prepaid'
    OVO = 'OVO'
    GOPAY = 'GoPay'
    LINKAJA = 'LinkAja'
    DANA = 'DANA'
    SHOPEEPAY = 'ShopeePay'
    TRAIN_TICKET = 'tiket_kereta'
    WATER_BILL = 'tagihan_air'

    @classmethod
    def not_auto_retry_category(cls):
        return cls.POSTPAID + cls.BPJS_KESEHATAN + (cls.ELECTRICITY_PREPAID, )

    @classmethod
    def xfers_ewallet_products(cls):
        return [cls.DANA]


class TransactionMethodCode():
    Method = namedtuple(
        'Method',
        [
            'code',
            'name'
        ]
    )

    SELF = Method(1, 'self')
    OTHER = Method(2, 'other')
    PULSA_N_PAKET_DATA = Method(3, 'pulsa & paket data')
    PASCA_BAYAR = Method(4, 'pasca bayar')
    DOMPET_DIGITAL = Method(5, 'dompet digital')
    LISTRIK_PLN = Method(6, 'listrik pln')
    BPJS_KESEHATAN = Method(7, 'bpjs kesehatan')
    E_COMMERCE = Method(8, 'e-commerce')
    QRIS = Method(9, 'qris')
    CREDIT_CARD = Method(10, 'kartu kredit')
    TRAIN_TICKET = Method(11, 'tiket kereta')
    PDAM = Method(12, 'pdam')
    EDUCATION = Method(13, 'education')
    BALANCE_CONSOLIDATION = Method(14, 'balance_consolidation')
    HEALTHCARE = Method(15, 'healthcare')
    INTERNET_BILL = Method(16, 'internet bill')
    JFINANCING = Method(17, 'j-financing')
    PFM = Method(18, 'pfm')
    QRIS_1 = Method(19, 'qris_1')

    BFI = -1
    ALL_PRODUCT = -3

    @classmethod
    def code_from_name(cls, method_name: str) -> int:
        """
        Transaction method ID from the method name
        e.g. 'self' => 1
        """
        for attr in dir(cls):
            value = getattr(cls, attr)
            if isinstance(value, cls.Method) and value.name == method_name:
                return value.code
        raise ValueError(f"Method name '{method_name}' not found.")

    @classmethod
    def name_from_code(cls, method_code: str) -> int:
        """
        Transaction method ID from the method name
        e.g. '1' => 'self'
        """
        for attr in dir(cls):
            value = getattr(cls, attr)
            if isinstance(value, cls.Method) and value.code == method_code:
                return value.name
        raise ValueError(f"Transaction Method Code '{method_code}' not found.")

    @classmethod
    def all(cls):
        return [
            cls.SELF,
            cls.OTHER,
            cls.PULSA_N_PAKET_DATA,
            cls.PASCA_BAYAR,
            cls.DOMPET_DIGITAL,
            cls.LISTRIK_PLN,
            cls.BPJS_KESEHATAN,
            cls.E_COMMERCE,
            cls.QRIS,
            # cls.CREDIT_CARD,
            cls.TRAIN_TICKET,
            cls.PDAM,
            cls.EDUCATION,
            cls.BALANCE_CONSOLIDATION,
            cls.HEALTHCARE,
            cls.INTERNET_BILL,
            cls.JFINANCING,
            cls.PFM,
            cls.QRIS_1,
        ]

    @classmethod
    def all_code(cls):
        return [transaction_method.code for transaction_method in cls.all()]

    @classmethod
    def all_name(cls):
        return [transaction_method.name for transaction_method in cls.all()]

    @classmethod
    def choices(cls):
        return [
            (transaction_method.code, transaction_method.name) for transaction_method in cls.all()
        ]

    @classmethod
    def new_products(cls):
        return []

    @classmethod
    def cash(cls):
        return [cls.SELF.code, cls.OTHER.code]

    @classmethod
    def payment_point(cls):
        return [
            cls.PULSA_N_PAKET_DATA.code,
            cls.PASCA_BAYAR.code,
            cls.DOMPET_DIGITAL.code,
            cls.LISTRIK_PLN.code,
            cls.BPJS_KESEHATAN.code,
            cls.PDAM.code,
            cls.TRAIN_TICKET.code,
            cls.INTERNET_BILL.code,
        ]

    @classmethod
    def single_step_disbursement(cls):
        return cls.payment_point() + [cls.QRIS.code, cls.CREDIT_CARD.code]

    @classmethod
    def draft_loan(cls):
        return [cls.QRIS.code]

    @classmethod
    def partner_transaction_available(cls):
        return [cls.OTHER.code]

    @classmethod
    def mobile_transactions(cls):
        return [cls.PULSA_N_PAKET_DATA.code, cls.DOMPET_DIGITAL.code]

    @classmethod
    def require_bank_account_destination(cls):
        return [
            cls.SELF.code,
            cls.OTHER.code,
            cls.E_COMMERCE.code,
            cls.EDUCATION.code,
            cls.HEALTHCARE.code,
        ]

    @classmethod
    def require_bank_account_customer_validate(cls):
        return [cls.SELF.code, cls.OTHER.code]

    @classmethod
    def loan_purpose_base_transaction_method(cls):
        return [cls.OTHER.code, cls.PULSA_N_PAKET_DATA.code,
                cls.PASCA_BAYAR.code, cls.DOMPET_DIGITAL.code, cls.QRIS.code,
                cls.LISTRIK_PLN.code, cls.BPJS_KESEHATAN.code, cls.E_COMMERCE.code]

    @classmethod
    def not_show_product_skrtp(cls):
        return [
            cls.SELF.code,
            cls.OTHER.code,
            cls.BPJS_KESEHATAN.code,
            cls.PDAM.code,
            cls.TRAIN_TICKET.code,
            cls.EDUCATION.code
        ]

    @classmethod
    def inquire_sepulsa_need_validate(cls):
        return [
            cls.PASCA_BAYAR.code,
            cls.LISTRIK_PLN.code,  # prepaid & postpaid, but only need to validate when postpaid
            cls.BPJS_KESEHATAN.code,
            cls.PDAM.code,
            cls.INTERNET_BILL.code,
        ]

    @classmethod
    def swift_limit_transaction_codes(cls):
        return [
            cls.SELF.code,
            cls.PULSA_N_PAKET_DATA.code,
        ]

    @classmethod
    def mercury_transaction_codes(cls):
        """
        Cashloan methods for mercury (ana transaction model)
        """
        return [cls.SELF.code, cls.OTHER.code]

    @classmethod
    def mercury_transaction_names(cls):
        """
        Cashloan method names for mercury (ana transaction model)
        """
        return [cls.SELF.name, cls.OTHER.name]


class ErrorMessage:
    # An error occurred, please try again later
    GENERAL_FOR_REQUEST_EXCEPTION = 'Terjadi kesalahan, coba lagi nanti'
    NOT_ELIGIBLE_FOR_THE_TRANSACTION = 'Anda tidak dapat melakukan transaksi di metode ini'
    AVAILABLE_LIMIT = (
        'Pastikan Limitmu tidak kurang dari nominal transaksi yang ingin kamu lakukan, ya.'
    )
    EWALLET_NOT_AVAILABLE_OR_HAS_ISSUES = (
        'Saat ini produk dompet digital sedang tidak tersedia '
        'atau sedang bermasalah, mohon cek beberapa saat lagi'
    )


class SepulsaAdminFee:
    TRAINT_ICKET = 7500


class TrainTicketStatus:
    PENDING = "Pending"
    CANCELED = "Batal"
    FAILED = "Gagal"
    DONE = "Selesai"


class SepulsaMessage:
    WRONG_NUMBER_MOBILE_EWALLET = "Nomor Handphone"
    WRONG_NUMBER_BPJS = "Nomor BPJS"
    WRONG_NUMBER_ELECTRICITY = "Nomor meter/ ID pelanggan"
    BILL_ALREADY_PAID = "Tagihan sudah terbayarkan"
    PRODUCT_ISSUE = "Terjadi kesalahan pada sistem, cobalah beberapa saat lagi"
    GENERAL_ERROR_MOBILE = (
        'Pastikan nomor HP yang kamu masukkan benar. '
        'Jika sudah benar dan tagihan tidak muncul, artinya tagihanmu sudah terbayar.'
    )
    TRAIN_ROUTE_NOT_FOUND = [
        "Tiket untuk Rute ini Tidak Ditemukan",
        "Coba ubah tanggal atau stasiun asal dan tujuannya, ya!",
    ]
    PRODUCT_CLOSED_TEMPORARILY = "Produk sedang diperbarui, silakan coba lagi nanti"
    INVALID = "Terjadi kesalahan, data tidak valid"
    READ_TIMEOUT_ERROR = ["Waktu Proses Berakhir", "Kamu bisa ulangi prosesnya dari awal, kok."]
    GENERAL_ERROR_TRAIN_TICKET = [
        "Maaf, Sistem Kami Mengalami Masalah",
        "Silakan coba lagi dalam beberapa saat dan masukkan lagi rute yang kamu cari, ya!",
    ]
    PRODUCT_NOT_FOUND = 'Produk tidak ditemukan'


class SepulsaHTTPRequestType:
    POST = 'post'
    GET = 'get'


class InternetBillCategory:
    TELKOM = 'telkom'
    POSTPAID_INTERNET = 'postpaid_internet'


class XfersEWalletConst:
    PREFIX_ACCOUNT_NUMBER = "8528"
    PERMATA_BANK_NAME = "BANK PERMATA, Tbk"
