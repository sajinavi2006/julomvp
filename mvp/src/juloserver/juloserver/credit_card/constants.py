from argparse import Namespace

from juloserver.julo.statuses import CreditCardCodes


class CreditCardStatusConstant:
    UNASSIGNED = 'unassigned'
    ASSIGNED = 'assigned'
    ACTIVE = 'active'
    BLOCKED = 'blocked'
    CLOSED = 'closed'
    ELIGIBLE_RESUBMISSION = 'eligible_resubmission'

    @classmethod
    def all_status(cls):
        return {
            cls.UNASSIGNED, cls.CLOSED, cls.ACTIVE, cls.BLOCKED, cls.ASSIGNED
        }


class ErrorMessage:
    CREDIT_CARD_NOT_FOUND = 'JULO Card tidak ditemukan'
    FAILED_PROCESS = 'gagal diproses'
    INVALID = 'tidak valid'
    WRONG_PASSWORD_OR_USERNAME = "username atau password yang anda masukkan salah."
    INCORRECT_OTP = "OTP salah"
    CARD_NUMBER_INVALID = "Nomor kartu salah/tidak ditemukan"
    CARD_APPLICATION_ID_INVALID = "Card application id salah/tidak ditemukan"
    CARD_APPLICATION_HAS_CARD_NUMBER = "Card application sudah mempunyai card number"
    CARD_NUMBER_NOT_AVAILABLE = "Nomor kartu sudah tidak available, " \
                                "silahkan gunakan nomor kartu lainnya"
    FAILED_PIN_RELATED = "Terjadi kesalahan. Mohon cek kembali PIN Anda " \
                         "atau coba dalam beberapa saat lagi"


MAX_RETRY_RECHECK_INQUIRY_CARD_STATUS = 10
RETRY_RECHECK_INQUIRY_CARD_STATUS_DELAY = 60  # seconds


class OTPConstant:
    TRANSACTION_TYPE = Namespace(**{'new_pin': 'newPIN',
                                    'reset_pin': 'resetPIN'})
    ACTION_TYPE = Namespace(**{'new_pin': 'credit_card_new_pin',
                               'reset_pin': 'credit_card_reset_pin'})


class BSSResponseConstant:
    TRANSACTION_SUCCESS = {'code': '00', 'description': 'Transaksi Sukses'}
    LIMIT_INSUFFICIENT = {'code': '04', 'description': 'Saldo tidak cukup'}
    CARD_NOT_REGISTERED = {'code': 'C0', 'description': 'Nomor Kartu tidak terdaftar'}
    CARD_INACTIVE = {'code': '02', 'description': 'Rekening tidak aktif'}
    TRANSACTION_FAILED = {'code': '24', 'description': 'Transaksi tidak dapat diproses'}
    TRANSACTION_TIMEOUT = {'code': '68', 'description': 'Transaksi timeout'}
    TRANSACTION_NOT_FOUND = {'code': '29', 'description': 'Transaksi tidak ditemukan'}
    DATA_NOT_COMPLETE = {'code': '27', 'description': 'Data message tidak lengkap'}


class BSSTransactionConstant:
    EDC = 'DEBIT.EDC'
    DECLINE_FEE = 'DECLINE.FEE'

    @classmethod
    def eligible_transactions(cls):
        return {cls.EDC, cls.DECLINE_FEE}


class FeatureNameConst(object):
    CREDIT_CARD_BLOCK_REASON = 'credit_card_block_reason'
    CREDIT_CARD_FAQ = 'credit_card_faq'
    JULO_CARD_WHITELIST = 'julo_card_whitelist'
    JULO_CARD_ON_OFF = 'julo_card_on_off'


class PushNotificationContentsConst:
    class Emoticons:
        PLANE = "\U0001F6EB"
        SELFIE = "\U0001F933"
        PARTYING_FACE = "\U0001F973"
        CROSSED_EYE = "\U0001F635"
        HUG_FACE = "\U0001F917"
        PARTY_POPPER = "\U0001F389"
        MONEY_MOUTH_FACE = "\U0001F911"

    STATUSES = {
        CreditCardCodes.CARD_ON_SHIPPING: {
            'title': 'Kartu menuju rumahmu!{}'.format(Emoticons.PLANE),
            'body': 'JULO Card sudah dikirim. Silahkan menunggu, ya!',
            'template_code': 'credit_card_status_changed_530'
        },
        CreditCardCodes.CARD_ACTIVATED: {
            'title': 'Selamat! JULO Card kamu sudah aktif{}'.format(Emoticons.PARTYING_FACE),
            'body': 'Hore! Kamu bisa nikmati transaksi pakai JULO Card',
            'template_code': 'credit_card_status_changed_580'
        },
        CreditCardCodes.CARD_RECEIVED_BY_USER: {
            'title': 'Segera aktivasi JULO Card{}'.format(Emoticons.SELFIE),
            'body': 'Tinggal sedikit lagi! Yuk, aktivasi kartumu sekarang.',
            'template_code': 'credit_card_status_changed_540'
        },
        CreditCardCodes.RESUBMIT_SELFIE: {
            'title': 'Data kamu sedang dalam proses review',
            'body': 'Silakan submit ulang selfie maupun alamat '
                    'untuk melewati proses review lebih cepat.',
            'template_code': 'credit_card_status_changed_523'
        },
        CreditCardCodes.CARD_OUT_OF_STOCK: {
            'title': 'Kartu dalam tahap pembuatan',
            'body': 'Tunggu, ya. Kami masih dalam proses pembuatan kartu. '
                    'Kamu pasti akan kebagian kok.',
            'template_code': 'credit_card_status_changed_505'
        },
        CreditCardCodes.CARD_BLOCKED: {
            'title': 'Berhasil memblokir kartu',
            'body': 'Kartu telah berhasil diblokir demi keamanan.',
            'template_code': 'credit_card_status_changed_581'
        },
        CreditCardCodes.CARD_UNBLOCKED: {
            'title': 'Kartu siap dibuka kembali',
            'body': 'Kamu sudah siap membuka blokir kartumu. '
                    'Jangan lupa masukan PIN kartu untuk melanjutkan.',
            'template_code': 'credit_card_status_changed_582'
        },
    }

    CHANGE_TENOR = {
        'title': 'Kamu bisa ubah cicilan kamu, loh!{}'.format(Emoticons.HUG_FACE),
        'body': 'Mudah! atur sendiri cicilan transaksi',
        'template_code': 'notification_julo_card_change_tenor',
        'destination': "julo_card_choose_tenor"
    }
    TRANSACTION_COMPLETED = {
        'title': 'Asik, Transaksimu Berhasil! {}'.format(Emoticons.PARTY_POPPER),
        'body': 'Secara otomatis, tenor terpilih adalah '
                '{} bulan, ya! Terima kasih',
        'template_code': 'notification_julo_card_transaction_completed',
        'destination': "julo_card_transaction_completed"
    }
    INCORRECT_PIN_WARNING = {
        'title': 'Hati-Hati Kartumu Terblokir',
        'body': 'Kamu sudah salah memasukkan PIN 2 kali di hari ini, '
                'mohon berhati-hati dalam memasukkan PIN atau kartu mu akan terblokir',
        'template_code': 'julo_card_incorrect_pin_warning'
    }
    INFORM_FIRST_TRANSACTION_CASHBACK = {
        'title': 'Cashback {}% untuk Transaksi '
                 'Pertamamu pakai JULO Card! {}',
        'body': 'Yuk, transaksi pakai JULO Card dan cashback maks. Rp{} ribu untukmu, tanpa tapi!',
        'template_code': 'notification_julo_card_inform_first_transaction_cashback',
    }
    OBTAINED_FIRST_TRANSACTION_CASHBACK = {
        'title': 'Asik, Cashback dari Transaksi Pertamamu Pakai JULO Card Sudah Kamu Terima!',
        'body': 'Gunakan terus JULO Card dan dapatkan promo menarik lainnya, ya!',
        'template_code': 'notification_julo_card_obtained_first_transaction_cashback',
        'destination': "cashback_transaction"
    }


class ReasonCardApplicationHistory:
    CUSTOMER_TRIGGERED = 'customer_triggered'
