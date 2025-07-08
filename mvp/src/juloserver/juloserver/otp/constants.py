class MisCallOTPStatus:
    REQUEST = 'request'
    PROCESSED = 'processed'
    FINISHED = 'finished'


class OTPRequestStatus:
    SUCCESS = 'success'
    LIMIT_EXCEEDED = 'limit_exceeded'
    RESEND_TIME_INSUFFICIENT = 'resend_time_insufficient'
    FEATURE_NOT_ACTIVE = 'feature_not_active'
    PHONE_NUMBER_NOT_EXISTED = 'phone_number_not_existed'
    PHONE_NUMBER_DIFFERENT = 'phone_number_different'
    EMAIL_NOT_EXISTED = 'email_not_existed'
    PHONE_NUMBER_2_CONFLICT_PHONE_NUMBER_1 = 'phone_number_2_conflict_phone_number_1'
    PHONE_NUMBER_2_CONFLICT_REGISTER_PHONE = 'phone_number_conflict_register_phone'


class OTPValidateStatus:
    SUCCESS = 'success'
    FAILED = 'failed'
    LIMIT_EXCEEDED = 'limit_exceeded'
    FEATURE_NOT_ACTIVE = 'inactive'
    ANDROID_ID_MISMATCH = 'android_id_mismatch'
    EXPIRED = 'expired'
    PHONE_NUMBER_MISMATCH = 'phone_number_mismatch'
    IOS_ID_MISMATCH = 'ios_id_mismatch'

    @classmethod
    def error_statuses(cls):
        return [cls.FAILED, cls.FEATURE_NOT_ACTIVE, cls.ANDROID_ID_MISMATCH, cls.EXPIRED]


class OTPType:
    SMS = 'sms'
    MISCALL = 'miscall'
    EMAIL = 'email'
    WHATSAPP = 'whatsapp'
    OTPLESS = 'otpless'
    ALL_ACTIVE_TYPE = (SMS, MISCALL, EMAIL, WHATSAPP, OTPLESS)


class SessionTokenType:
    LONG_LIVED = 'long_lived'
    SHORT_LIVED = 'short_lived'


class SessionTokenAction:
    LOGIN = 'login'
    REGISTER = 'register'
    PHONE_REGISTER = 'phone_register'
    CASHBACK_GOPAY = 'cashback_gopay'
    CASHBACK_SEPULSA = 'cashback_sepulsa'
    CASHBACK_PAYMENT = 'cashback_payment'
    CASHBACK_BANK_TRANSFER = 'cashback_bank_transfer'
    ADD_BANK_ACCOUNT_DESTINATION = 'add_bank_account_destination'
    VERIFY_PHONE_NUMBER = 'verify_phone_number'
    VERIFY_EMAIL = 'verify_email'
    VERIFY_PHONE_NUMBER_2 = 'verify_phone_number_2'
    VERIFY_SUSPICIOUS_LOGIN = 'verify_suspicious_login'
    CHANGE_PHONE_NUMBER = 'change_phone_number'
    TRANSACTION_TARIK_DANA = 'transaction_self'
    TRANSACTION_TRANSFER_DANA = 'transaction_other'
    TRANSACTION_LISTRIK_PLN = 'transaction_listrik_pln'
    TRANSACTION_PULSA_DAN_DATA = 'transaction_pulsa_dan_data'
    TRANSACTION_ECOMMERCE = 'transaction_ecommerce'
    TRANSACTION_DOMPET_DIGITAL = 'transaction_dompet_digital'
    TRANSACTION_BPJS_KESEHATAN = 'transaction_bpjs_kesehatan'
    TRANSACTION_PASCA_BAYAR = 'transaction_pasca_bayar'
    TRANSACTION_QRIS = 'transaction_qris'
    TRANSACTION_PDAM = 'transaction_pdam'
    TRANSACTION_TRAIN_TICKET = 'transaction_train_ticket'
    TRANSACTION_EDUCATION = 'transaction_education'
    TRANSACTION_HEALTHCARE = 'transaction_healthcare'
    TRANSACTION_INTERNET_BILL = 'transaction_internet_bill'
    TRANSACTION_JFINANCING = 'transaction_j_financing'
    TRANSACTION_PFM = 'transaction_pfm'
    TRANSACTION_QRIS_1 = 'transaction_qris_1'
    AUTODEBET_BRI_DEACTIVATION = 'autodebet_bri_deactivation'
    PRE_LOGIN_RESET_PIN = 'pre_login_reset_pin'
    PRE_LOGIN_CHANGE_PHONE = 'pre_login_change_phone'
    PAYLATER_REGISTER = 'paylater_register'
    ACCOUNT_DELETION_REQUEST = 'account_deletion_request'
    CONSENT_WITHDRAWAL_REQUEST = 'consent_withdrawal_request'
    PARTNERSHIP_REGISTER_VERIFY_EMAIL = 'partnership_register_verify_email'
    LEADGEN_STANDARD_REGISTER_VERIFY_EMAIL = 'leadgen_standard_register_verify_email'
    TRANSACTION_ACTIONS = [
        TRANSACTION_TARIK_DANA,
        TRANSACTION_TRANSFER_DANA,
        TRANSACTION_LISTRIK_PLN,
        TRANSACTION_PULSA_DAN_DATA,
        TRANSACTION_ECOMMERCE,
        TRANSACTION_DOMPET_DIGITAL,
        TRANSACTION_BPJS_KESEHATAN,
        TRANSACTION_PASCA_BAYAR,
        TRANSACTION_QRIS,
        TRANSACTION_PDAM,
        TRANSACTION_EDUCATION,
        TRANSACTION_TRAIN_TICKET,
        TRANSACTION_HEALTHCARE,
        TRANSACTION_INTERNET_BILL,
        TRANSACTION_JFINANCING,
        TRANSACTION_PFM,
        TRANSACTION_QRIS_1,
    ]
    PHONE_ACTIONS = [
        LOGIN,
        CASHBACK_GOPAY,
        CASHBACK_SEPULSA,
        CASHBACK_PAYMENT,
        CASHBACK_BANK_TRANSFER,
        ADD_BANK_ACCOUNT_DESTINATION,
        VERIFY_PHONE_NUMBER,
        CHANGE_PHONE_NUMBER,
        *TRANSACTION_ACTIONS,
        VERIFY_PHONE_NUMBER_2,
        AUTODEBET_BRI_DEACTIVATION,
        PRE_LOGIN_RESET_PIN,
        PRE_LOGIN_CHANGE_PHONE,
        PHONE_REGISTER,
        ACCOUNT_DELETION_REQUEST,
        CONSENT_WITHDRAWAL_REQUEST,
    ]
    WHATSAPP_ACTIONS = [
        VERIFY_PHONE_NUMBER,
        VERIFY_PHONE_NUMBER_2,
        LOGIN,
        PRE_LOGIN_RESET_PIN,
        TRANSACTION_TARIK_DANA,
        TRANSACTION_DOMPET_DIGITAL,
        ADD_BANK_ACCOUNT_DESTINATION,
        ACCOUNT_DELETION_REQUEST,
        TRANSACTION_PULSA_DAN_DATA,
        PHONE_REGISTER,
        REGISTER,
        CHANGE_PHONE_NUMBER,
        TRANSACTION_LISTRIK_PLN,
        TRANSACTION_ECOMMERCE,
        PRE_LOGIN_CHANGE_PHONE,
        TRANSACTION_TRANSFER_DANA,
        TRANSACTION_EDUCATION,
        TRANSACTION_PASCA_BAYAR,
        TRANSACTION_PDAM,
        TRANSACTION_BPJS_KESEHATAN,
        TRANSACTION_TRAIN_TICKET,
        TRANSACTION_HEALTHCARE,
        TRANSACTION_QRIS_1,
        CONSENT_WITHDRAWAL_REQUEST,
    ]
    OTPLESS_ACTIONS = [VERIFY_PHONE_NUMBER, VERIFY_PHONE_NUMBER_2]
    EMAIL_ACTIONS = [
        VERIFY_EMAIL,
        VERIFY_SUSPICIOUS_LOGIN,
        ACCOUNT_DELETION_REQUEST,
        CONSENT_WITHDRAWAL_REQUEST,
    ]
    NON_CUSTOMER_ACTIONS = [
        PHONE_REGISTER,
        PAYLATER_REGISTER,
        PARTNERSHIP_REGISTER_VERIFY_EMAIL,
        LEADGEN_STANDARD_REGISTER_VERIFY_EMAIL,
    ]
    COMPULSORY_OTP_ACTIONS = [PHONE_REGISTER, PRE_LOGIN_RESET_PIN]
    NO_AUTH_OTP_ACTION_TYPES = [PHONE_REGISTER, PRE_LOGIN_RESET_PIN, PRE_LOGIN_CHANGE_PHONE]
    SKIP_OTP_ACTIONS = [LOGIN]
    ALLOW_RAW_CREDENTIAL_ACTIONS = [LOGIN, VERIFY_SUSPICIOUS_LOGIN]
    PAYLATER_LINKING = 'paylater_linking'
    TRANSACTION_METHOD_ID = {
        TRANSACTION_TARIK_DANA: 1,
        TRANSACTION_TRANSFER_DANA: 2,
        TRANSACTION_PULSA_DAN_DATA: 3,
        TRANSACTION_PASCA_BAYAR: 4,
        TRANSACTION_DOMPET_DIGITAL: 5,
        TRANSACTION_LISTRIK_PLN: 6,
        TRANSACTION_BPJS_KESEHATAN: 7,
        TRANSACTION_ECOMMERCE: 8,
        TRANSACTION_QRIS: 9,
        TRANSACTION_TRAIN_TICKET: 11,
        TRANSACTION_PDAM: 12,
        TRANSACTION_EDUCATION: 13,
        TRANSACTION_HEALTHCARE: 15,
        TRANSACTION_INTERNET_BILL: 16,
        TRANSACTION_JFINANCING: 17,
        TRANSACTION_PFM: 18,
        TRANSACTION_QRIS_1: 19,
    }
    OTP_SWITCH_ACTIONS = [
        LOGIN,
        VERIFY_PHONE_NUMBER,
        PRE_LOGIN_RESET_PIN,
        VERIFY_SUSPICIOUS_LOGIN,
        TRANSACTION_TARIK_DANA,
        TRANSACTION_DOMPET_DIGITAL,
        ADD_BANK_ACCOUNT_DESTINATION,
        ACCOUNT_DELETION_REQUEST,
        TRANSACTION_PULSA_DAN_DATA,
        VERIFY_PHONE_NUMBER_2,
        VERIFY_EMAIL,
        PHONE_REGISTER,
        REGISTER,
        CHANGE_PHONE_NUMBER,
        TRANSACTION_LISTRIK_PLN,
        TRANSACTION_ECOMMERCE,
        PRE_LOGIN_CHANGE_PHONE,
        TRANSACTION_TRANSFER_DANA,
        TRANSACTION_EDUCATION,
        AUTODEBET_BRI_DEACTIVATION,
        TRANSACTION_PASCA_BAYAR,
        TRANSACTION_PDAM,
        TRANSACTION_BPJS_KESEHATAN,
        TRANSACTION_TRAIN_TICKET,
        TRANSACTION_HEALTHCARE,
        TRANSACTION_QRIS_1,
        CONSENT_WITHDRAWAL_REQUEST,
    ]


class TransactionRiskStatus:
    SAFE = None
    UNSAFE = 1


class OTPResponseHTTPStatusCode:
    CREATED = 200
    SUCCESS = 201
    RESEND_TIME_INSUFFICIENT = 425
    LIMIT_EXCEEDED = 429
    SERVER_ERROR = 500
    REQUIRE_MORE_OTP_STEP = 428


otp_validate_message_map = {
    OTPValidateStatus.SUCCESS: 'success',
    OTPValidateStatus.FAILED: 'Kode OTP yang kamu masukkan salah',
    OTPValidateStatus.LIMIT_EXCEEDED: 'Kesempatan mencoba OTP sudah habis, '
    'coba kembali beberapa saat lagi',
    OTPValidateStatus.FEATURE_NOT_ACTIVE: 'OTP yang Anda masukkan salah',
    OTPValidateStatus.EXPIRED: 'OTP telah kadaluarsa. Silahkan kirim ulang permintaan kode OTP',
    OTPValidateStatus.ANDROID_ID_MISMATCH: (
        "Permintaan OTP kamu saat ini tidak dapat diproses. "
        "Mohon menghubungi CS JULO di cs@julo.co.id untuk info lebih lanjut."
    ),
    OTPValidateStatus.PHONE_NUMBER_MISMATCH: 'Kamu baru saja melakukan '
    'permintaan OTP untuk nomor {phone_number}. Silakan lakukan permintaan beberapa saat lagi.',
    OTPValidateStatus.IOS_ID_MISMATCH: (
        "Permintaan OTP kamu saat ini tidak dapat diproses. "
        "Mohon menghubungi CS JULO di cs@julo.co.id untuk info lebih lanjut."
    ),
}


# CITCALL Client
class CitcallApi:
    ASYNC_CALL = '/v3/motp'
    BACKUP_ASYNC_CALL = "/gateway/v3/motp"
    CALLBACK = '/api/otp/v1/miscall-callback/'


class CitcallResponseCode:
    SUCCESS = 0
    UNKNOW_ERROR = 6
    INVALID_GATEWAY = 7
    INSUFFICIENT_AMOUNT = 14
    SERVICE_TEMPORARY_AVAILABLE = 34
    INVALID_MSISDN = 42
    INVALID_SMS_CONTENT = 43
    SENDERID_CLOSED = 44
    MAINTENANCE_IN_PROGRESS = 66
    WRONG_PASSWORD = 76
    USERID_NOT_FOUND = 77
    DATA_NOT_FOUND = 78
    INVALID_TOKEN = 79
    EXPIRED_TOKEN = 80
    MAXIMUM_TRY_REACHED = 81
    MISSING_PARAMETER = 88
    APIKEY_NOT_FOUND = 96
    INVALID_JSON_FORMAT = 97
    AUTHORIZATION_FAILED = 98
    WRONG_METHOD = 99


class CitcallRetryGatewayType:
    INDO = 1


class EmailOTP:
    EMAIL_OTP_BASE_URL = 'https://julostatics.oss-ap-southeast-5.aliyuncs.com/common/otp/'
    BANNER_URL = EMAIL_OTP_BASE_URL + 'banner.png'
    FOOTER_URL = EMAIL_OTP_BASE_URL + 'footer.png'
    SUBJECT = 'Jangan berikan kode ini ke siapapun'
    TEMPLATE = 'email_otp.html'
    EMAIL_FROM = 'cs@julo.co.id'
    NAME_FROM = 'JULO'
    REPLY_TO = 'cs@julo.co.id'
    CHANGE_OTP_TEMPLATE_CODE = 'email_change_otp'
    FRAUD_OTP_TEMPLATE_CODE = 'login_fraud_otp'
    PAYLATER_LINKING_TEMPLATE_CODE = 'paylater_linking_otp'
    REGISTER = 'register'
    OTP_SWITCH = 'otp_switch'
    OTP_SWITCH_SUBJECT = 'Ini Kode OTP Kamu'
    CONTACT_PHONE_DISPLAYS = ['021-50919034', '021-50919035']
    VERIFY_EMAIL_HEADER = (
        'Masukkan kode OTP ini di aplikasi JULO untuk melanjutkan pergantian '
        'email. Valid untuk {life_time_minutes} menit. Kode OTP adalah:'
    )
    SUSPICIOUS_LOGIN_HEADER = (
        'Demi keamanan akun Anda, silahkan masukkan kode OTP berikut '
        'untuk dapat melanjutkan proses login. Valid untuk '
        '{life_time_minutes} menit. Kode OTP adalah:'
    )
    VERIFY_REGISTER_HEADER = (
        'Masukkan kode OTP ini di aplikasi JULO untuk melanjutkan proses '
        'register. Valid untuk {life_time_minutes} menit. Kode OTP adalah:'
    )
    PAYLATER_LINKING_EMAIL_HEADER = (
        'Masukkan kode OTP ini di aplikasi JULO untuk melanjutkan proses '
        'linking. Valid untuk {life_time_minutes} menit. Kode OTP adalah:'
    )
    PAYLATER_LINKING_SUBJECT = 'Verifikasi OTP untuk Hubungkan Akunmu'
    PAYLATER_LINKING_TEMPLATE = 'email_otp_paylater_linking.html'
    OTP_SWITCH_HEADER = (
        'Silakan masukkan kode OTP ini untuk dapat melanjutkan proses yang sedang kamu lakukan di '
        'aplikasi JULO.'
    )
    DEEPLINK_TEMPLATE = 'deeplink_email_otp.html'
    DEEPLINK_TEMPLATE_CODE = 'email_otp_deeplink'
    PREFILL_EMAIL_OTP_HEADER_TEXT = 'Di bawah ini adalah OTP kamu untuk digunakan di\
                                    Aplikasi JULO. Yuk, klik\
                                    <b>Gunakan OTP</b> untuk masukkan kode\
                                    secara otomatis ke aplikasi JULO kamu!'
    PREFILL_EMAIL_OTP_FOOTER_TEXT = 'Jika email ini diakses dari\
                                    <b>perangkat berbeda</b>, harap masukkan\
                                    kode di atas <b>secara manual</b> di\
                                    aplikasi JULO kamu.'
    NEW_EMAIL_OTP_HEADER_TEXT = 'Di Bawah ini adalah OTP kamu untuk digunakan di Aplikasi JULO.'
    NEW_EMAIL_OTP_FOOTER_TEXT = (
        'Harap  masukan kode di atas <b>secara manual</b> di aplikasi JULO kamu.'
    )


class FeatureSettingName:
    NORMAL = 'otp_setting'
    COMPULSORY = 'compulsory_otp_setting'
    SENDGRID_BOUNCE_TAKEOUT = 'sendgrid_bounce_takeout'
    OTP_BYPASS = 'otp_bypass'


otp_service_type_action_type_map = {
    OTPType.SMS: SessionTokenAction.PHONE_ACTIONS,
    OTPType.MISCALL: SessionTokenAction.PHONE_ACTIONS,
    OTPType.EMAIL: SessionTokenAction.EMAIL_ACTIONS,
    OTPType.WHATSAPP: SessionTokenAction.WHATSAPP_ACTIONS,
    OTPType.OTPLESS: SessionTokenAction.OTPLESS_ACTIONS,
}

otp_service_type_linked_map = {
    OTPType.SMS: [OTPType.SMS, OTPType.MISCALL],
    OTPType.MISCALL: [OTPType.SMS, OTPType.MISCALL],
    OTPType.EMAIL: [OTPType.EMAIL],
    OTPType.WHATSAPP: [OTPType.WHATSAPP],
    OTPType.OTPLESS: [OTPType.OTPLESS],
}

action_type_otp_service_type_map = {
    SessionTokenAction.LOGIN: [OTPType.SMS, OTPType.MISCALL, OTPType.WHATSAPP],
    SessionTokenAction.CASHBACK_GOPAY: [OTPType.SMS, OTPType.MISCALL],
    SessionTokenAction.CASHBACK_SEPULSA: [OTPType.SMS, OTPType.MISCALL],
    SessionTokenAction.CASHBACK_PAYMENT: [OTPType.SMS, OTPType.MISCALL],
    SessionTokenAction.CASHBACK_BANK_TRANSFER: [OTPType.SMS, OTPType.MISCALL],
    SessionTokenAction.ADD_BANK_ACCOUNT_DESTINATION: [
        OTPType.SMS,
        OTPType.MISCALL,
        OTPType.WHATSAPP,
    ],
    SessionTokenAction.VERIFY_PHONE_NUMBER: [
        OTPType.SMS,
        OTPType.MISCALL,
        OTPType.WHATSAPP,
        OTPType.OTPLESS,
    ],
    SessionTokenAction.VERIFY_EMAIL: [OTPType.EMAIL],
    SessionTokenAction.VERIFY_PHONE_NUMBER_2: [OTPType.SMS, OTPType.MISCALL, OTPType.WHATSAPP],
    SessionTokenAction.VERIFY_SUSPICIOUS_LOGIN: [OTPType.EMAIL],
    SessionTokenAction.CHANGE_PHONE_NUMBER: [OTPType.SMS, OTPType.WHATSAPP, OTPType.MISCALL],
    SessionTokenAction.TRANSACTION_TARIK_DANA: [OTPType.SMS, OTPType.MISCALL, OTPType.WHATSAPP],
    SessionTokenAction.TRANSACTION_TRANSFER_DANA: [OTPType.SMS, OTPType.MISCALL, OTPType.WHATSAPP],
    SessionTokenAction.TRANSACTION_LISTRIK_PLN: [OTPType.SMS, OTPType.MISCALL, OTPType.WHATSAPP],
    SessionTokenAction.TRANSACTION_PULSA_DAN_DATA: [OTPType.SMS, OTPType.MISCALL, OTPType.WHATSAPP],
    SessionTokenAction.TRANSACTION_ECOMMERCE: [OTPType.SMS, OTPType.MISCALL, OTPType.WHATSAPP],
    SessionTokenAction.TRANSACTION_DOMPET_DIGITAL: [OTPType.SMS, OTPType.MISCALL, OTPType.WHATSAPP],
    SessionTokenAction.TRANSACTION_BPJS_KESEHATAN: [OTPType.SMS, OTPType.MISCALL, OTPType.WHATSAPP],
    SessionTokenAction.TRANSACTION_PASCA_BAYAR: [OTPType.SMS, OTPType.MISCALL, OTPType.WHATSAPP],
    SessionTokenAction.TRANSACTION_QRIS: [OTPType.SMS, OTPType.MISCALL],
    SessionTokenAction.TRANSACTION_PDAM: [OTPType.SMS, OTPType.MISCALL, OTPType.WHATSAPP],
    SessionTokenAction.TRANSACTION_TRAIN_TICKET: [OTPType.SMS, OTPType.MISCALL, OTPType.WHATSAPP],
    SessionTokenAction.TRANSACTION_EDUCATION: [OTPType.SMS, OTPType.MISCALL, OTPType.WHATSAPP],
    SessionTokenAction.TRANSACTION_HEALTHCARE: [OTPType.SMS, OTPType.MISCALL, OTPType.WHATSAPP],
    SessionTokenAction.TRANSACTION_INTERNET_BILL: [OTPType.SMS, OTPType.MISCALL],
    SessionTokenAction.TRANSACTION_JFINANCING: [OTPType.SMS, OTPType.MISCALL],
    SessionTokenAction.TRANSACTION_PFM: [OTPType.SMS, OTPType.MISCALL],
    SessionTokenAction.TRANSACTION_QRIS_1: [OTPType.SMS, OTPType.MISCALL],
    SessionTokenAction.AUTODEBET_BRI_DEACTIVATION: [OTPType.SMS, OTPType.WHATSAPP],
    SessionTokenAction.PRE_LOGIN_RESET_PIN: [OTPType.SMS, OTPType.MISCALL, OTPType.WHATSAPP],
    SessionTokenAction.PRE_LOGIN_CHANGE_PHONE: [OTPType.SMS, OTPType.WHATSAPP],
    SessionTokenAction.PHONE_REGISTER: [OTPType.SMS, OTPType.MISCALL, OTPType.WHATSAPP],
    SessionTokenAction.ACCOUNT_DELETION_REQUEST: [
        OTPType.SMS,
        OTPType.MISCALL,
        OTPType.EMAIL,
        OTPType.WHATSAPP,
    ],
    SessionTokenAction.CONSENT_WITHDRAWAL_REQUEST: [
        OTPType.SMS,
        OTPType.MISCALL,
        OTPType.EMAIL,
        OTPType.WHATSAPP,
    ],
}

ALLOW_RAW_CREDENTIAL_ACTIONS = [
    SessionTokenAction.LOGIN,
    SessionTokenAction.VERIFY_SUSPICIOUS_LOGIN,
]

multilevel_otp_action_config = {
    SessionTokenAction.LOGIN: {
        'otp_types': [OTPType.EMAIL],
        'action_type': SessionTokenAction.VERIFY_SUSPICIOUS_LOGIN,
    }
}


class LupaPinConstants:
    OTP_LIMIT_EXCEEDED = 'Permintaan ubah PIN udah mencapai batas maksimum. \
        Coba lagi di hari berikutnya, ya.'


failed_action_type_otp_message_map = {
    SessionTokenAction.PRE_LOGIN_RESET_PIN: {
        'title': 'Ubah PIN Gagal',
        'message': 'Maaf, ada kesalahan di sistem kami. Silakan ulangi beberapa saat lagi, ya!',
    },
    SessionTokenAction.PRE_LOGIN_CHANGE_PHONE: {
        'title': 'Ubah Nomor HP Gagal',
        'message': 'Maaf, ada kesalahan di sistem kami. Silakan ulangi beberapa saat lagi, ya!',
    },
}

OUTDATED_OLD_VERSION = (
    "Fitur ini hanya dapat diakses dengan aplikasi versi terbaru. Update JULO "
    "dulu, yuk! Untuk info lebih lanjut, hubungi CS: <br><br>"
    "Telepon: <br>"
    "<b>021-5091 9034/021-5091 9035</b> <br><br>"
    "Email: <br>"
    "<b>cs@julo.co.id</b>"
)


class RedisKey(object):
    WHATSAPP_INSTALL_STATUS = 'otp_service:{}:whatsapp_installed'
