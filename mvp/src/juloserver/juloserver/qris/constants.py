from collections import namedtuple


class DokuAccountStatus:
    UNREGISTERED = 'un-registered'
    DONE = 'done'


class DokuResponseCode:
    SUCCESS = "0000"

class QrisTransactionStatus:
    SUCCESS = "success"
    FAILED = "failed"
    PENDING = "pending"
    CANCELLED = "cancelled"

    ALL = (
        (SUCCESS, SUCCESS),
        (FAILED, FAILED),
        (PENDING, PENDING),
        (CANCELLED, CANCELLED),
    )

    @classmethod
    def amar_status_path_check(cls, from_status: str, to_status: str) -> bool:
        """
        Check all possible AMAR transaction status paths
        """
        status_path = {
            cls.PENDING: {cls.SUCCESS, cls.FAILED, cls.CANCELLED},
            cls.FAILED: set(),
            cls.SUCCESS: set(),
            cls.CANCELLED: set(),
        }
        if from_status in status_path.keys():
            if to_status in status_path[from_status]:
                return True

        return False

    @classmethod
    def get_statuses_for_transaction_history(cls):
        """
        Return statuses that are considered 'active' or relevant for filtering transactions.
        """
        return [cls.SUCCESS, cls.PENDING, cls.FAILED]


class QrisResponseMessages:
    LINKING_ACCOUNT_ERROR = ("Terjadi kesalahan saat melakukan scan QR. "
                             "Silahkan coba beberapa saat lagi")
    INVALID_OTP = "Kode yang Anda masukan salah."
    BLACKLISTED_MERCHANT = "Merchant's QR is blacklisted"


class QrisLinkageStatus:
    REQUESTED = "requested"
    SUCCESS = "success"
    FAILED = "failed"
    IGNORED = "ignored"  # this means status doesn't matter in the flow for a partner (AMAR, etc)
    INACTIVE = "inactive"  # no longer active (us setting it manually, etc)
    REGIS_FORM = (
        "register_form"  # user's reached regist form, after requested, before success/failed
    )

    ALL = (
        (REQUESTED, REQUESTED),
        (SUCCESS, SUCCESS),
        (FAILED, FAILED),
        (IGNORED, IGNORED),
        (INACTIVE, INACTIVE),
        (REGIS_FORM, REGIS_FORM),
    )

    @classmethod
    def amar_status_path_check(cls, from_status: str, to_status: str) -> bool:
        """
        Check all possible AMAR status paths
        """
        status_path = {
            cls.REQUESTED: {cls.SUCCESS, cls.FAILED, cls.REGIS_FORM},
            cls.FAILED: {cls.SUCCESS, cls.FAILED},  # can have multiple failures
            cls.SUCCESS: set(),
            cls.REGIS_FORM: {cls.SUCCESS, cls.FAILED},
        }
        if from_status in status_path.keys():
            if to_status in status_path[from_status]:
                return True
        return False


class QrisProductName:
    Product = namedtuple('Product', ['code', 'name'])
    QRIS = Product(1, 'QRIS')


LIMIT_QRIS_TRANSACTION_MONTHS = 6
HASH_DIGI_SIGN_FORMAT = "PPFP-{}"


class AmarCallbackConst:
    class AccountRegister:
        """
        Account register webhook
        https://docs-embedded.amarbank.co.id/banking-widget/webhook/bank-account-registration
        """

        ACCEPTED_STATUS = "accepted"
        REJECTED_STATUS = "rejected"

        REGISTER_TYPE = "new"
        LOGIN_TYPE = "existing"

        @classmethod
        def statuses(cls):
            return [cls.ACCEPTED_STATUS, cls.REJECTED_STATUS]

        @classmethod
        def types(cls):
            return [cls.REGISTER_TYPE, cls.LOGIN_TYPE]

    class LoanDisbursement:
        """
        QRIS Transaction Status
        https://docs-embedded.amarbank.co.id/banking-widget/webhook/qris-transaction-status
        """

        SUCESS_STATUS = "00"
        FAIL_STATUS = "01"
        PENDING_STATUS = "02"
        SERVICE_ID = "EB_QRIS_STATUS"

        @classmethod
        def statuses(cls):
            return [cls.SUCESS_STATUS, cls.FAIL_STATUS, cls.PENDING_STATUS]


class QrisFeDisplayedStatus:
    PENDING = "Sedang diproses"
    SUCCESS = "Berhasil"
    FAILED = "Gagal"


class QrisTransactionStatusColor:
    GREEN = "#1E7461"
    YELLOW = "#F69539"
    RED = "#DB4D3D"


class QrisStatusImageLinks:
    PENDING = "https://statics.julo.co.id/qris/sedang_diproses.png"
    SUCCESS = "https://statics.julo.co.id/qris/berhasil.png"
    FAILED = "https://statics.julo.co.id/qris/gagal.png"


class AmarRejection:
    class Code:
        ZERO_LIVENESS = "zeroLiveness"
        NAME_SCORE_LOW = "nameScoreLow"
        BIRTHDAY_SCORE_LOW = "birthDateScoreLow"
        BLANK_EKTP = "blankEKTP"
        FACEMATCH_DUKCAPIL_SCORE_LOW = "facematchDukcapilScoreLow"
        FAMILY_CARD = "familyCard"
        NIK_NOT_FOUND = "nikNotFound"
        EKTP_BLACKLIST_AREA = "eKTPBlacklistArea"

    @classmethod
    def get_message(cls, code) -> str:
        default_message = (
            "Mohon pastikan data yang Anda masukkan sudah benar. "
            "Jika masalah berlanjut, hubungi layanan pelanggan kami untuk bantuan lebih lanjut."
        )

        mapping = {
            cls.Code.ZERO_LIVENESS: (
                "Verifikasi wajah gagal. Sistem tidak mendeteksi wajah Anda dengan jelas. "
                "Pastikan wajah Anda terlihat dengan baik dan ulangi proses verifikasi."
            ),
            cls.Code.NAME_SCORE_LOW: (
                "Nama tidak valid. Nama Anda tidak sesuai dengan data di Dukcapil. "
                "Pastikan Anda memasukkan nama lengkap sesuai e-KTP."
            ),
            cls.Code.BIRTHDAY_SCORE_LOW: (
                "Tanggal lahir tidak valid. "
                "Harap pastikan tanggal lahir yang Anda masukkan sesuai dengan data di e-KTP Anda."
            ),
            cls.Code.BLANK_EKTP: (
                "Data e-KTP tidak ditemukan. "
                "Pastikan Anda mengunggah foto e-KTP dengan jelas dan lengkap."
            ),
            cls.Code.FACEMATCH_DUKCAPIL_SCORE_LOW: (
                "Verifikasi wajah gagal. Wajah Anda tidak cocok dengan data Dukcapil. "
                "Silakan coba lagi dengan pencahayaan yang baik dan posisi wajah yang jelas."
            ),
            cls.Code.NIK_NOT_FOUND: (
                "NIK tidak ditemukan. "
                "Pastikan nomor NIK yang Anda masukkan benar dan sesuai dengan e-KTP Anda."
            ),
            cls.Code.FAMILY_CARD: (
                "Verifikasi Kartu Keluarga diperlukan. "
                "Pastikan Anda mengunggah foto Kartu Keluarga yang sesuai dengan data e-KTP Anda."
            ),
        }

        return mapping.get(code, default_message)
