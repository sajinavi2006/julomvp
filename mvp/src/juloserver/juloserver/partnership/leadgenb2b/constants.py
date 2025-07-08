from juloserver.otp.constants import OTPType, SessionTokenAction


class LeadgenFeatureSetting:
    API_CONFIG = "partnership_leadgen_api_config"


class LeadgenStandardRejectReason:
    LOCKED = {
        'title': 'NIK/Email Kamu Diblokir',
        "description": "Kamu sudah beberapa kali memasukkan NIK / Email yang "
        "tidak valid atau sudah terdaftar. Silakan coba lagi"
        " dengan NIK / email berbeda dalam 3 jam ke depan.",
    }
    USER_REGISTERED = {
        'title': "NIK / Email Tidak Valid atau Sudah Terdaftar",
        "description": "Silakan masuk lewat akunmu atau gunakan NIK / email "
        "yang valid dan belum terdaftar di JULO, ya.",
    }
    GENERAL_LOGIN_ERROR = "Email, NIK, atau PIN kamu salah."
    LOGIN_ATTEMP_FAILED = (
        'Kamu telah {attempt_count} kali salah memasukan informasi. '
        + '{max_attempt} kali salah akan memblokir sementara akun kamu.'
    )
    NOT_LEADGEN_APPLICATION = (
        "Akunmu tidak bisa masuk lewat JULO versi web. "
        "Silakan masuk lewat aplikasi JULO di HP kamu, ya!"
    )
    USER_NOT_FOUND = "Akun tidak ditemukan"
    OTP_REQUEST_GENERAL_ERROR = "Permintaan OTP tidak dapat diproses, mohon coba beberapa saat lagi"
    NOT_LEADGEN_APPLICATION = (
        "Akunmu tidak bisa masuk lewat JULO versi web. "
        "Silakan masuk lewat aplikasi JULO di HP kamu, ya!"
    )
    OTP_VALIDATE_GENERAL_ERROR = "OTP yang kamu masukkan salah"
    OTP_VALIDATE_ATTEMPT_FAILED = (
        "Kode OTP salah. Kamu punya kesempatan coba {attempt_left} kali lagi."
    )
    OTP_VALIDATE_EXPIRED = "OTP yang kamu masukkan sudah kedaluwarsa"
    OTP_VALIDATE_MAX_ATTEMPT = (
        "Kamu salah memasukkan OTP {max_attempt} kali. Harap tunggu dan minta OTP yang baru, ya."
    )
    ERROR_REQUEST_RATE_LIMIT = 'Terlalu banyak percobaan, silahkan mencoba beberapa saat lagi'
    OTP_REGISTER_REQUIRED = "Kamu belum melakukan verifikasi OTP"
    CHANGE_PIN_BLOCKED = 'Permintaan perubahan pin anda ditolak, mohon menunggu selama 1 jam'
    DATA_NOT_FOUND = 'Data Tidak Ditemukan'


SUSPICIOUS_LOGIN_DISTANCE = 100  # kilometer


class PinReturnCode(object):
    OK = 'ok'
    UNAVAILABLE = 'unavailable'
    FAILED = 'failed'
    LOCKED = 'locked'
    PERMANENT_LOCKED = 'permanent_locked'


class PinResetReason(object):
    FROZEN = 'frozen reset'
    CORRECT_PIN = 'correct PIN reset'
    FORGET_PIN = 'forget PIN reset'


class VerifyPinMsg(object):
    LOGIN_FAILED = 'Email, NIK, atau PIN kamu salah'
    WRONG_PIN = 'PIN salah, mohon periksa kembali'
    PIN_IS_TOO_WEAK = 'PIN tidak boleh angka berulang atau berurutan'


ALLOWED_IMAGE_EXTENSIONS = {"jpg", "jpeg", "png", "webp"}
UPLOAD_IMAGE_MAX_SIZE = 1024 * 1024 * 3
IMAGE_EXPIRY_DURATION = 600  # seconds
IMAGE_SOURCE_TYPE_MAPPING = {
    "ktp": "ktp_self",
    "ktp-selfie": "selfie",
    "payslip": "payslip",
    "bank-statement": "bank_statement",
}


# reference from src/juloserver/juloserver/julo/statuses.py:1029
LEADGEN_MAPPED_RESUBMIT_DOCS_REASON = {
    'ktp needed': 'ktp',
    'ktp blurry': 'ktp',
    'salary doc needed': 'payslip',
    'salary doc blurry': 'payslip',
    'selfie needed': 'ktpSelfie',
    'selfie blurry': 'ktpSelfie',
    'mutasi rekening needed': 'bankStatement',
}

LEADGEN_MAPPED_RESUBMIT_DOCS_TYPE = {
    'ktp': 'personalIdentity',
    'ktpSelfie': 'personalIdentity',
    'payslip': 'mandatoryDocs',
    'bankStatement': 'mandatoryDocs',
}

leadgen_otp_service_type_linked_map = {
    OTPType.SMS: [OTPType.SMS],
    OTPType.EMAIL: [OTPType.EMAIL],
}

leadgen_action_type_otp_service_type_map = {
    SessionTokenAction.LOGIN: [OTPType.EMAIL],
    SessionTokenAction.VERIFY_PHONE_NUMBER: [OTPType.SMS],
    SessionTokenAction.LEADGEN_STANDARD_REGISTER_VERIFY_EMAIL: [OTPType.EMAIL],
    SessionTokenAction.PRE_LOGIN_RESET_PIN: [OTPType.EMAIL],
}


class LeadgenStandardApplicationFormType:
    PRE_REGISTER_CONFIRMATION = "pre_register_confirmation"
    PERSONAL_IDENTITY = "personal_identity"
    EMERGENCY_CONTACT = "emergency_contact"
    JOB_INFORMATION = "job_information"
    PERSONAL_FINANCE_INFORMATION = "personal_finance_information"
    FORM_SUBMISSION = "form_submission"


MAPPING_FORM_TYPE = {
    LeadgenStandardApplicationFormType.PRE_REGISTER_CONFIRMATION: 0,
    LeadgenStandardApplicationFormType.PERSONAL_IDENTITY: 1,
    LeadgenStandardApplicationFormType.EMERGENCY_CONTACT: 2,
    LeadgenStandardApplicationFormType.JOB_INFORMATION: 3,
    LeadgenStandardApplicationFormType.PERSONAL_FINANCE_INFORMATION: 4,
    LeadgenStandardApplicationFormType.FORM_SUBMISSION: 5,
}

IMAGE_TYPE_MAPPING_CAMEL_TO_SNAKE_CASE = {
    "ktp": "ktp_self",
    "ktpSelfie": "selfie",
    "payslip": "payslip",
    "bankStatement": "bank_statement",
}


class ValidateUsernameReturnCode(object):
    OK = 'ok'
    UNAVAILABLE = 'unavailable'
    FAILED = 'failed'
    LOCKED = 'locked'
    PERMANENT_LOCKED = 'permanent_locked'
