from builtins import object
from collections import namedtuple


SWEEPING_SAFE_INTERVAL = 3600  # in seconds


class AutodebetStatuses(object):
    PENDING_REVOCATION = 'pending_revocation'
    PENDING_REGISTRATION = 'pending_registration'
    FAILED_REGISTRATION = 'failed_registration'
    FAILED_REVOCATION = 'failed_revocation'
    REVOKED = 'revoked'
    REGISTERED = 'registered'


class FeatureNameConst(object):
    AUTODEBET_BCA = 'autodebet_bca'
    AUTODEBET_BRI = 'autodebet_bri'
    WHITELIST_AUTODEBET_BCA = 'whitelist_autodebet_bca'
    BENEFIT_AUTODEBET_BCA = 'benefit_autodebet_bca'
    RETRY_AUTODEBET_BCA_INQUIRY = 'retry_autodebet_bca_inquiry'
    CASHBACK_AUTODEBET_BCA = 'cashback_autodebet_bca'
    TUTORIAL_AUTODEBET_BCA = 'tutorial_autodebet_bca'
    AUTODEBET_BCA_WELCOME = "autodebet_bca_welcome"
    AUTODEBET_GOPAY = 'autodebet_gopay'
    AUTODEBET_MANDIRI = 'autodebet_mandiri'
    AUTODEBET_MANDIRI_MAX_LIMIT_DEDUCTION_DAY = 'autodebet_mandiri_max_limit_deduction_day'
    AUTODEBET_BNI = 'autodebet_bni'
    AUTODEBET_DANA = 'autodebet_dana'
    AUTODEBET_OVO = 'autodebet_ovo'
    BCA_AUTODEBET_DEACTTIVATE_WARNING = 'bca_autodebet_deactivate_warning'

    # AUTODEBET BRI
    RETRY_AUTODEBET_BRI = 'retry_autodebet_bri'
    WHITELIST_AUTODEBET_BRI = 'whitelist_autodebet_bri'
    AUTODEBET_TESTING_ERROR = 'autodebet_testing_error'
    AUTODEBET_BRI_WELCOME = "autodebet_bri_welcome"

    WHITELIST_AUTODEBET_GOPAY = 'whitelist_autodebet_gopay'
    WHITELIST_AUTODEBET_MANDIRI = 'whitelist_autodebet_mandiri'
    WHITELIST_AUTODEBET_BNI = 'whitelist_autodebet_bni'
    WHITELIST_AUTODEBET_DANA = 'whitelist_autodebet_dana'
    WHITELIST_AUTODEBET_OVO = 'whitelist_autodebet_ovo'

    INSUFFICIENT_BALANCE_TURN_OFF = "insufficient_balance_turn_off"
    MANDIRI_SLACK_ALERT_PAYMENT_NOTIFICATION = "mandiri_slack_alert_payment_notification"
    AUTODEBET_BNI_MAX_LIMIT_DEDUCTION_DAY = "autodebet_bni_max_limit_deduction_day"

    # AUTODEBET TNC
    BCA_AUTODEBET_TNC = "bca_autodebet_tnc"
    BRI_AUTODEBET_TNC = "bri_autodebet_tnc"
    GOPAY_AUTODEBET_TNC = "gopay_autodebet_tnc"
    MANDIRI_AUTODEBET_TNC = "mandiri_autodebet_tnc"
    BNI_AUTODEBET_TNC = "bni_autodebet_tnc"
    DANA_AUTODEBET_TNC = "dana_autodebet_tnc"
    OVO_AUTODEBET_TNC = "ovo_autodebet_tnc"

    AUTODEBET_RE_INQUIRY = "re_inquiry_autodebet"
    AUTODEBET_IDFY_WHITELIST = 'autodebet_idfy_whitelist'

    REPAYMENT_DETOKENIZE = "repayment_detokenize"
    AUTODEBET_PAYMENT_OFFER_CONTENT = 'autodebet_payment_offer_content'
    DELAY_AUTODEBET_BCA_DEDUCTION = 'delay_autodebet_bca_deduction'


class AutodebetVendorConst(object):
    BCA = 'BCA'
    BRI = 'BRI'
    GOPAY = 'GOPAY'
    MANDIRI = 'MANDIRI'
    BNI = 'BNI'
    DANA = 'DANA'
    OVO = 'OVO'
    LIST = (
        BCA,
        BRI,
        GOPAY,
        MANDIRI,
        BNI,
        DANA,
        OVO,
    )
    PAYMENT_METHOD = {
        BRI: '002',
        BCA: '014',
        GOPAY: '017',
        MANDIRI: '008',
        BNI: '009',
        DANA: '1005',
        OVO: '1006',
    }
    BCA_PAYMENT_METHOD_CODE = '999014'
    BRI_PAYMENT_METHOD_CODE = '999002'
    GOPAY_PAYMENT_METHOD_CODE = '999017'
    MANDIRI_PAYMENT_METHOD_CODE = '999008'
    BNI_PAYMENT_METHOD_CODE = '999009'
    DANA_PAYMENT_METHOD_CODE = '9991005'

    @classmethod
    def get_all_payment_method_code(cls):
        return {
            cls.BCA_PAYMENT_METHOD_CODE,
            cls.BRI_PAYMENT_METHOD_CODE,
            cls.GOPAY_PAYMENT_METHOD_CODE,
            cls.MANDIRI_PAYMENT_METHOD_CODE,
            cls.BNI_PAYMENT_METHOD_CODE,
            cls.DANA_PAYMENT_METHOD_CODE,
        }


class VendorConst(object):
    BCA = 'BCA'
    BRI = 'BRI'
    GOPAY = 'GOPAY'
    MANDIRI = 'MANDIRI'
    BNI = 'BNI'
    DANA = 'DANA'
    OVO = 'OVO'
    LIST = (BCA, BRI, GOPAY, MANDIRI, BNI, DANA, OVO)
    AUTODEBET_BY_VENDOR = [
        {
            'vendor': BCA,
            'name': FeatureNameConst.AUTODEBET_BCA,
            'whitelist': FeatureNameConst.WHITELIST_AUTODEBET_BCA,
            'payment_method_code': AutodebetVendorConst.BCA_PAYMENT_METHOD_CODE,
        },
        {
            'vendor': BRI,
            'name': FeatureNameConst.AUTODEBET_BRI,
            'whitelist': FeatureNameConst.WHITELIST_AUTODEBET_BRI,
            'payment_method_code': AutodebetVendorConst.BRI_PAYMENT_METHOD_CODE,
        },
        {
            'vendor': GOPAY,
            'name': FeatureNameConst.AUTODEBET_GOPAY,
            'whitelist': FeatureNameConst.WHITELIST_AUTODEBET_GOPAY,
            'payment_method_code': AutodebetVendorConst.GOPAY_PAYMENT_METHOD_CODE,
        },
        {
            'vendor': MANDIRI,
            'name': FeatureNameConst.AUTODEBET_MANDIRI,
            'whitelist': FeatureNameConst.WHITELIST_AUTODEBET_MANDIRI,
            'payment_method_code': AutodebetVendorConst.MANDIRI_PAYMENT_METHOD_CODE,
        },
        {
            'vendor': BNI,
            'name': FeatureNameConst.AUTODEBET_BNI,
            'whitelist': FeatureNameConst.WHITELIST_AUTODEBET_BNI,
            'payment_method_code': AutodebetVendorConst.BNI_PAYMENT_METHOD_CODE,
        },
        {
            'vendor': DANA,
            'name': FeatureNameConst.AUTODEBET_DANA,
            'whitelist': FeatureNameConst.WHITELIST_AUTODEBET_DANA,
            'payment_method_code': AutodebetVendorConst.DANA_PAYMENT_METHOD_CODE,
        },
        {
            'vendor': OVO,
            'name': FeatureNameConst.AUTODEBET_OVO,
            'whitelist': FeatureNameConst.WHITELIST_AUTODEBET_OVO,
        },
    ]
    MAX_DUE_AMOUNT_BRI_AUTODEBET = 999999
    AMOUNT_DEDUCTION_BRI_AUTODEBET = 900000
    AUTODEBET_MANDIRI_PURCHASE_PRODUCT_TYPE = '05'

    VENDOR_CHOICES = (
        ("BCA", "BCA"),
        ("BRI", "BRI"),
        ("GOPAY", "GOPAY"),
        ("MANDIRI", "MANDIRI"),
        ("BNI", "BNI"),
        ("DANA", "DANA"),
        ("OVO", "OVO")
    )
    VENDOR_INSUFFICIENT_SUSPEND = (BCA, BRI, GOPAY, BNI, MANDIRI, DANA, OVO)
    VENDOR_DEACTIVATE_WARNING = BCA


class BCASpecificConst(object):
    REGISTRATION_ATTEMPT_DAILY_LIMIT = 5


class TutorialAutodebetConst(object):
    VENDOR = [
        AutodebetVendorConst.BCA,
        AutodebetVendorConst.BRI,
        AutodebetVendorConst.GOPAY,
        AutodebetVendorConst.MANDIRI,
        AutodebetVendorConst.BNI,
        AutodebetVendorConst.DANA,
        AutodebetVendorConst.OVO,
    ]
    FEATURE_SETTING_NAME = 'tutorial_autodebet'
    AUTODEBET_TYPES = [
        'registration',
        'revocation',
        'benefit',
    ]
    AUTODEBET_CONTENTS = [
        'content_type',
        'cta_type',
        'cta',
        'video',
        'subtitle',
    ]
    BENEFIT_TYPE = [
        'cashback',
        'waive_interest',
    ]


class CallbackAuthorizationErrorResponseConst(object):
    ERR111 = {
        "error_code": "111",
        "error_message": {
            "indonesian": "Merchant ID tidak tersedia.",
            "english": "Merchant ID mismatch.",
        },
    }

    ERR444 = {
        "error_code": "444",
        "error_message": {
            "indonesian": "Request ID tidak tersedia.",
            "english": "Request ID mismatch.",
        },
    }

    ERR888 = {
        "error_code": "888",
        "error_message": {
            "indonesian": "Tidak memiliki akses.",
            "english": "Unauthorized.",
        },
    }

    ERR999 = {
        "error_code": "999",
        "error_message": {
            "indonesian": "Sistem sedang dalam perbaikan. Silahkan coba beberapa saat lagi.",
            "english": "System is under maintenance. Please try again later.",
        },
    }

    ERR000 = {
        "error_code": "000",
        "error_message": {
            "indonesian": "Sistem sedang dalam perbaikan. Silahkan coba beberapa saat lagi.",
            "english": "System is under maintenance. Please try again later.",
        },
    }


class BRITransactionStatus:
    FAILED = "FAILED"
    SUCCESS = "SUCCESS"
    OTP_PENDING = "OTP PENDING"
    CALLBACK_PENDING = "CALLBACK PENDING"
    INITIAL = "INITIAL"
    CANCEL = "CANCEL"
    PENDING = "PENDING"
    COMPLETED = "COMPLETED"


class BRITransactionCallbackStatus:
    FAILED = "FAILED"
    COMPLETED = "COMPLETED"
    PENDING = "PENDING"


class BRIErrorCode:
    INVALID_ACCOUNT_DETAILS = 'INVALID_ACCOUNT_DETAILS'
    INSUFFICIENT_BALANCE = 'INSUFFICIENT_BALANCE'
    INVALID_PAYMENT_METHOD_ERROR = 'INVALID_PAYMENT_METHOD_ERROR'


class CallbackOTPValidationRegistration:
    ERROR_MESSAGE = {
        "DATA_NOT_FOUND_ERROR": {
            "error_code": 404,
            "error_messsage": "Token yang diberikan belum diaktifasi untuk akun ini.",
        },
        "INVALID_OTP_ERROR": {"error_code": 400, "error_message": "OTP yang kamu masukkan salah."},
        "EXPIRED_OTP_ERROR": {"error_code": 400, "error_message": "OTP sudah tidak berlaku."},
        "MAX_OTP_ATTEMPTS_ERROR": {
            "error_code": 400,
            "error_message": "Kamu sudah melewati batas percobaan OTP.",
        },
    }


class RedisKey(object):
    CLIENT_AUTH_TOKEN = 'autodebet:bca_client_auth_token'
    MANDIRI_CLIENT_AUTH_TOKEN = 'autodebet:mandiri_client_auth_token'
    BNI_CLIENT_B2B_TOKEN = 'autodebet:bni_client_b2b_token'
    BNI_CLIENT_B2B2C_TOKEN = 'autodebet:bni_client_b2b2c_token:'
    BNI_AYOCONNECT_TOKEN = 'autodebet:bni_ayoconnect_token:'
    IDFY_NOTIFICATION_FLAG = 'autodebet:idfy_notification_flag:'
    AUTODEBET_FUND_COLLECTION_TASK_BCA_COUNTER = 'autodebet_fund_collection_task_bca_counter'


class ExperimentConst(object):
    BEST_DEDUCTION_TIME_ADBCA_EXPERIMENT_CODE = 'best_deduction_time_adbca_experiment'
    SMS_REMINDER_AUTODEBET_EXPERIMENT_CODE = 'SmsReminderAutodebet'
    SMS_REMINDER_AUTODEBET_EXPERIMENT_NAME = 'sms reminder autodebet experiment'


class AutodebetDeductionSourceConst(object):
    BANK_SCRAPE_SALARY_DAY = 'bank_scrape_salary_day'
    APPLICATION_PAYDAY = 'application_payday'
    ORIGINAL_CYCLE_DAY = 'original_cycle_day'
    FOLLOW_PAYDAY = 'payday'
    FOLLOW_DUE_DATE = 'due_date'


class MobileFeatureNameConstant(object):
    AUTODEBET_REMINDER_SETTING = 'autodebet_reminder_setting'


class AutodebetBenefitConst(object):
    AUTODEBET_BENEFIT = ['cashback', 'waive_interest']


class AutodebetTncVersionConst(object):
    VERSION_V2 = 'v2'
    VERSION_V3 = 'v3'

    LIST = [VERSION_V2, VERSION_V3]


class AutodebetMandiriResponseMessageConst(object):
    ERROR_MESSAGE = {
        '4030105': 'Aktivitas tidak wajar terdeteksi di akunmu.'
                   ' Silakan coba beberapa saat lagi, ya.',
        ('4030107', '4030407', '4038107'): 'Kartu kamu sudah terblokir. '
                                           'Silakan coba lagi di hari berikutnya, ya.',
        '4030108': 'Masa berlaku kartu kamu sudah habis',
        '4030109': 'Rekening kamu terdeteksi tidak aktif',
        '4030118': 'Masa berlaku kartu kamu sudah habis',
        '4030412': 'Klik Kirim Ulang dan masukkan kode OTP terbaru, ya',
        '4040415': 'Harap masukkan kode OTP yang benar, ya',
        '4038111': 'Silakan coba ulang dalam 1 jam lagi, ya',
        '4040111': 'Data yang kamu masukkan tidak valid',
        '5000100': 'Silakan coba beberapa saat lagi, ya',
        '5000105': 'Rekening kamu sudah terdaftar di JULO',
        '4030405': 'Kamu salah memasukkan kode OTP 3 kali. Silakan coba lagi di hari berikutnya,'
        ' ya.',
    }


REACTIVATION_VERSION_VENDOR = {
    AutodebetVendorConst.BRI: "8.21.0",
    AutodebetVendorConst.GOPAY: "8.22.0",
    # PLEASE UPDATE BELOW LATER BASED ON RELEASE VERSION
    AutodebetVendorConst.MANDIRI: "8.25.0",
    AutodebetVendorConst.BNI: "8.24.0",
    AutodebetVendorConst.DANA: "8.32.0",
}


class GopayErrorCode:
    INSUFFICIENT_BALANCE = 'Insufficient Balance'
    NOT_ENOUGH_BALANCE = 'NOT_ENOUGH_BALANCE'


class AutodebetBNIResponseCodeConst:
    SUCCESS_GET_AUTH_CODE = '2003000'
    SUCCESS_REGISTRATION_ACCOUNT_BIND = '2003100'
    DO_NOT_HONOR = '4033005'
    SUCCESS_HOST_TO_HOST = ['2003300', '2023300']
    FAILED_INSUFFICIENT_FUND = '4033304'
    FAILED_INSUFFICIENT_FUND_CALLBACK = '4030004'
    SUCCESS_GET_STATUS = '2003600'


class AutodebetBNIErrorMessageConst:
    AUTODEBET_HAS_ACTIVATED = "Account autodebet sedang aktif."
    GENERAL_ERROR = "Sedang terjadi kesalahan pada server. Silahkan coba beberapa saat lagi."
    AUTODEBET_ACCOUNT_NOT_FOUND = "Autodebet account tidak ditemukan."
    WRONG_OTP_THREE_TIMES = (
        "Kamu salah memasukan kode OTP sebanyak 3 kali. "
        "Silakan coba aktifkan Autodebet BNI lagi dalam 24 Jam ya!"
    )
    DO_NOT_HONOR = (
        'Kamu salah memasukkan kode OTP 3 kali. Silakan coba lagi di hari berikutnya,' ' ya.'
    )
    TRANSACTION_FAILED_OTP = 'Coba lagi beberapa saat dan masukkan kode OTP yang benar, ya'


class AutodebetBNILatestTransactionStatusConst:
    SUCCESS = 'success'
    FAILED = 'failed'
    PROCESSING = 'processing'


class BNICardBindCallbackResponseCodeMessageDescription:
    BNICardBindCallback = namedtuple('BNICardBindCallback',
                                     ['code', 'message', 'description'])

    SUCCESS = BNICardBindCallback("2000000", "Request has been processed successfully", None)
    CARD_NOT_FOUND = BNICardBindCallback("4040011", "Invalid Card", "Card was not found.")
    INVALID_FIELD = BNICardBindCallback("4000001", None, None)
    INTERNAL_SERVER_ERROR = BNICardBindCallback(
        "5000000",
        "INTERNAL SERVER ERROR",
        "There problem with our server. Please try again."
    )
    UNAUTHORIZED = BNICardBindCallback("4010000", 'Unauthorized', 'Unauthorized token')


class AutodebetBniUnbindingStatus(object):
    PENDING = 'PENDING'
    FAILED = 'FAILED'
    SUCCESS = 'SUCCESS'
    EXPIRED = 'EXPIRED'


class AutodebetBniOtpAction(object):
    UNBINDING = 'unbinding'
    PAYMENT = 'payment'


class BNIPurchaseCallbackResponseCodeMessageDescription:
    BNIPurchaseCallback = namedtuple('BNIPurchaseCallback', ['code', 'message', 'description'])
    SUCCESS = BNIPurchaseCallback("2000000", "Request has been processed successfully", None)
    BILL_NOT_FOUND = BNIPurchaseCallback("4040000", "Invalid Bill", "Bill not found")
    BILL_IS_PAID = BNIPurchaseCallback("4040000", "Paid Bill", "The bill has been paid")
    INTERNAL_SERVER_ERROR = BNIPurchaseCallback(
        "5000000", "INTERNAL SERVER ERROR", "There problem with our server. Please try again."
    )


class BNIErrorCode:
    INSUFFICIENT_FUND = "Insufficient Fund"


class AutodebetBNIPaymentResultStatusConst:
    SUCCESS = "success"
    PROCESSING = "processing"
    FAILED = "failed"
    INITIATED = "initiated"
    TIMEOUT = "timeout"
    PENDING_USER_VERIFICATION = "pending_user_verification"


class BCAErrorCode:
    INSUFFICIENT_FUND = 'Insufficient fund'


class DanaErrorCode:
    INSUFFICIENT_FUND = 'Insufficient Funds'


class OVOErrorCode:
    INSUFFICIENT_FUND = 'Insufficient Funds'


class BNIAyoConnectAccessTokenCodeMessageDescription:
    BNIAyoConnectAccessToken = namedtuple(
        'BNIAyoConnectAccessToken', ['code', 'message', 'description']
    )
    UNAUTHORIZED = BNIAyoConnectAccessToken(
        401, 'unauthorized', 'Client Id or client secret is not valid'
    )
    INVALID_FIELD = BNIAyoConnectAccessToken(400, None, None)
    INTERNAL_SERVER_ERROR = BNIAyoConnectAccessToken(
        500, "Internal Server Error", "There problem with our server. Please try again."
    )


class MandiriErrorCode:
    INSUFFICIENT_FUNDS = 'INSUFFICIENT FUNDS'


class AutodebetDanaResponseMessage:
    # ERROR RESPONSE
    AutodebetDanaResponse = namedtuple('AutodebetDanaResponse', ['code', 'message'])
    ALREADY_HAVE_ACTIVATED_AUTODEBET = AutodebetDanaResponse(406, 'Account autodebet sedang aktif')
    NOT_BIND_ACCOUNT = AutodebetDanaResponse(407, 'User has not bind dana account')
    PUBLIC_ID_NULL = AutodebetDanaResponse(408, 'Public Id is null')
    DUPLICATE_PUBLIC_ID = AutodebetDanaResponse(409, 'Duplicate public id')
    GENERAL_ERROR = AutodebetDanaResponse(
        410, 'Terjadi kesalahan, silahkan coba beberapa saat lagi'
    )
    AUTODEBET_HASNT_ACTIVATED_YET = AutodebetDanaResponse(
        410, 'Account autodebet belum pernah di aktivasi'
    )
    AUTODEBET_HAS_DEACTIVATED = AutodebetDanaResponse(411, 'Account autodebet tidak aktif')
    AUTODEBET_NOT_FOUND = AutodebetDanaResponse(412, 'Account autodebet tidak ditemukan')

    # SUCCESS RESPONSE
    SUCCESS_ACTIVATION = AutodebetDanaResponse(200, 'Aktivasi Dana Autodebet Berhasil!')
    SUCCESS_DEACTIVATION = AutodebetDanaResponse(200, 'Deaktivasi Dana Autodebet Berhasil!')


class AutodebetOvoResponseMessage:
    # ERROR RESPONSE
    AutodebetOvoResponse = namedtuple('AutodebetOvoResponse', ['code', 'message'])
    ALREADY_HAVE_ACTIVATED_AUTODEBET = AutodebetOvoResponse(406, 'Account autodebet sedang aktif')
    NOT_BIND_ACCOUNT = AutodebetOvoResponse(407, 'User has not bind OVO account')
    GENERAL_ERROR = AutodebetOvoResponse(
        410, 'Terjadi kesalahan, silahkan coba beberapa saat lagi'
    )
    AUTODEBET_HASNT_ACTIVATED_YET = AutodebetOvoResponse(
        410, 'Account autodebet belum pernah di aktivasi'
    )
    AUTODEBET_HAS_DEACTIVATED = AutodebetOvoResponse(411, 'Account autodebet tidak aktif')
    AUTODEBET_NOT_FOUND = AutodebetOvoResponse(412, 'Account autodebet tidak ditemukan')

    # SUCCESS RESPONSE
    SUCCESS_ACTIVATION = AutodebetOvoResponse(200, 'Aktivasi OVO Autodebet Berhasil!')
    SUCCESS_DEACTIVATION = AutodebetOvoResponse(200, 'Deaktivasi OVO Autodebet Berhasil!')


class AutodebetDANAPaymentResultStatusConst:
    """
    This is status payment from JULO side.
    """

    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    PENDING = "PENDING"


class LabelFieldsIDFyConst:
    """
    Format {fields_on_idfy / fields_on_db}
    """

    KEY_CAPTURE_PENDING = 'capture_pending'
    KEY_RECAPTURE_PENDING = 'recapture_pending'
    KEY_IN_PROGRESS = 'in_progress'
    KEY_REVIEW_REQUIRED = 'review_required'
    KEY_COMPLETED = 'completed'
    KEY_REJECTED = 'rejected'
    KEY_CANCELLED = 'cancelled'
    KEY_PURGED = 'purged'

    MAX_DAYS_IDFY_ALIVE = 30


class AutodebetOVOPaymentResultStatusConst:
    """
    This is status payment from JULO side.
    """
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    PENDING = "PENDING"


class AutodebetMandiriPaymentResultStatusConst:
    """
    This is status payment from JULO side.
    """

    SUCCESS = "success"
    FAILED = "failed"
    PENDING = "pending"


class AutodebetMandiriTransactionStatusCodeCons:
    """
    This is status transaction category code from OVO side.
    """

    SUCCESS = "00"
    INITIATED = "01"
    PAYING = "02"
    CANCELLED = "05"
    FAILED = "06"
    NOT_FOUND = "07"


class AutodebetMandiriResponseCodeConst:
    FAILED_INSUFFICIENT_FUND = '4035514'


class AutodebetDANATransactionStatusCodeCons:
    """
    This is status transaction category code from DANA side.
    """

    SUCCESS = "00"
    INITIATED = "01"
    PAYING = "02"
    CANCELLED = "05"
    NOT_FOUND = "07"


class AutodebetOVOTransactionStatusCodeCons:
    """
    This is status transaction category code from OVO side.
    """

    SUCCESS = "00"
    INITIATED = "01"
    PAYING = "02"
    CANCELLED = "05"
    FAILED = "06"
    NOT_FOUND = "07"


class DanaResponseMessage:
    GENERAL_ERROR = "General Error"
    INTERNAL_SERVER = "Internal Server Error"
    INVALID_FIELD_FORMAT = "Invalid Field Format"
    INVALID_MANDATORY_FIELD = "Invalid Mandatory Field"
    SUCCESSFUL = "Successful"
    UNAUTHORIZED = "Unauthorized."
    INVALID_TOKEN = "Invalid Token (B2B)"
    TRANSACTION_NOT_FOUND = "Transaction Not Found"


class DanaPaymentNotificationResponse:
    PaymentNotificationResponse = namedtuple('PaymentNotificationResponse', ['code', 'message'])

    SUCCESS = PaymentNotificationResponse("2005600", DanaResponseMessage.SUCCESSFUL)
    GENERAL_ERROR = PaymentNotificationResponse("5005600", DanaResponseMessage.GENERAL_ERROR)
    INTERNAL_SERVER = PaymentNotificationResponse("5005601", DanaResponseMessage.INTERNAL_SERVER)
    UNAUTHORIZED = PaymentNotificationResponse("4015600", DanaResponseMessage.UNAUTHORIZED)
    INVALID_TOKEN = PaymentNotificationResponse("4015601", DanaResponseMessage.INVALID_TOKEN)
    INVALID_MANDATORY_FIELD = PaymentNotificationResponse(
        "4005602", DanaResponseMessage.INVALID_MANDATORY_FIELD
    )
    INVALID_FIELD_FORMAT = PaymentNotificationResponse(
        "4005601", DanaResponseMessage.INVALID_FIELD_FORMAT
    )
    TRANSACTION_NOT_FOUND = PaymentNotificationResponse(
        "4045601", DanaResponseMessage.TRANSACTION_NOT_FOUND
    )


class AutodebetDanaResponseCodeConst:
    FAILED_INSUFFICIENT_FUND = '4035414'
    TRANSACTION_NOT_FOUND = '4045501'


MINIMUM_BALANCE_AUTODEBET_DANA_DEDUCTION_DPD = 10000
MINIMUM_BALANCE_AUTODEBET_OVO_DEDUCTION_DPD = 10000


class AutodebetOVOResponseCodeConst:
    FAILED_INSUFFICIENT_FUND = '4035414'
    TRANSACTION_NOT_FOUND = '4045501'
    EXCEEDS_TRANSACTION_AMOUNT_LIMIT = '4035402'


GENERAL_ERROR_MESSAGE = (
    'Maaf ya, terjadi masalah di sistem kami. ' 'Silahkan coba lagi dalam beberapa saat. ya!'
)
