from builtins import object

RECOMMEND_PASSWORD_CHANGE_MONTHS = 6
LOGIN_ATTEMPT_CLASSES = [
    'LoginJuloOne',
    'Login',
    'LoginV2',
    'LoginV3',
    'OTPCheckAllowed',
    'OtpRequest',
    'WebviewLogin',
    'LoginV4',
    'LoginV6',
    'LoginV7',
]
SUSPICIOUS_LOGIN_CHECK_CLASSES = [
    'LoginV7',
    'LoginV6',
    'LoginV4',
    'LoginV3',
    'LoginJuloOne',
    'WebviewLogin',
]
SUSPICIOUS_LOGIN_DISTANCE = 100  # kilometer


class VerifyPinMsg(object):
    USER_NOT_FOUND = 'Pengguna tidak ditemukan'
    REQUIRED_PIN = 'PIN diperlukan'
    NOT_JULO_ONE = 'Tidak tersedia'
    LOCKED = 'Terkunci, coba lagi nanti'
    LOCKED_LIMIT_TIME = (
        'Akun kamu diblokir sementara selama {hours} jam karena salah memasukkan '
        'informasi. Silakan coba kembali nanti.'
    )
    WRONG_PIN = 'PIN yang kamu ketik tidak sesuai'
    SUCCESS = 'OK'
    NO_FAILURE = (
        'Kamu telah {attempt_count} kali salah mengetik PIN. '
        + '{max_attempt} kali salah akan memblokir sementara akun kamu.'
    )
    LOGIN_FAILED = 'Email, NIK, Nomor Telepon, PIN, atau Kata Sandi kamu salah'
    PIN_IS_DOB = 'PIN tidak boleh menggunakan tanggal lahir'
    PIN_IS_TOO_WEAK = 'PIN tidak boleh menggunakan angka pengulangan atau berurutan'
    LOGIN_ATTEMP_FAILED = (
        'Kamu telah {attempt_count} kali salah memasukkan informasi. '
        + '{max_attempt} kali kesalahan membuat akunmu terblokir sementara waktu.'
    )
    PARTNERSHIP_LOGIN_ATTEMPT_FAILED = (
        'Kamu telah {attempt_count} kali salah memasukkan PIN. '
        + '{max_attempt} kali salah akan memblokir sementara akun kamu.'
    )
    PERMANENT_LOCKED = (
        'Akun kamu diblokir permanen karena salah memasukkan informasi secara '
        'terus menerus. Kamu bisa hubungi CS untuk info lebih lanjut.'
    )
    PIN_SAME_AS_OLD_PIN_RESET_PIN = (
        'Kata sandi yang kamu masukkan sama seperti sebelumnya. '
        'Mohon gunakan Kata sandi yang berbeda'
    )
    PIN_SAME_AS_OLD_PIN_FOR_CHANGE_PIN = 'PIN tidak boleh sama dengan PIN sebelumnya'
    IS_SUS_LOGIN = (
        'Saat ini kamu tidak bisa melakukan login karena kami '
        'menemukan masalah di akunmu. Mohon menghubungi '
        'CS JULO di cs@julo.co.id untuk info lebih lanjut'
    )

    RESET_KEY_EXPIRED = 'Link ubah PIN sudah kamu gunakan atau batas waktu habis. \
                        Ajukan permintaan ulang lewat aplikasi JULO di HP kamu untuk \
                        mengubah PIN, ya!'
    RESET_KEY_INVALID = 'Terjadi kesalahan. Silakan coba permintaan Lupa PIN kembali.'
    BLANK_PIN = 'PIN kosong.'
    BAD_PIN_FORMAT = 'PIN harus terdiri dari 6 digit.'
    PINS_ARE_NOT_THE_SAME = 'PIN tidak sama.'
    JULOVER_WEAK_PIN = (
        "Jangan gunakan PIN yang mudah ditebak seperti tanggal lahir, "
        "1111111, atau 222222. Silakan kembali ke aplikasi JULO untuk permintaan reset PIN ulang."
    )
    JULOVER_RESET_KEY_INVALID = (
        'Link yang kamu gunakan sudah tidak berlaku. '
        'Silakan kembali ke aplikasi JULO untuk permintaan reset PIN ulang.'
    )
    NO_LOCATION_DATA = 'Mohon ijinkan akses lokasi untuk dapat mengakses website JULO'
    LOCKED_LOGIN_REQUEST_LIMIT = (
        'Akun kamu diblokir sementara selama {eta} '
        'karena salah memasukkan informasi. Silakan coba masuk kembali nanti.'
    )
    PAYLATER_LOGIN_ATTEMP_FAILED = (
        '*Kamu telah {attempt_count} kali salah mengetik PIN. '
        + '{max_attempt} kali salah akan memblokir sementara akun kamu.'
    )
    GENERAL = 'Pastikan Input yang kamu masukkan benar'
    INVALID_RESET_KEY = 'Terjadi kesalahan. Silakan coba permintaan Lupa PIN kembali.'
    INVALID = 'Kembali ke halaman depan aplikasi JULO dan klik “Lupa PIN” untuk coba ubah lagi, ya!'
    SAME_AS_OLD_PIN = 'PIN Baru tidak boleh sama dengan PIN lama.'
    PREVIOUS_RESET_KEY = (
        'Silakan buka link di email permintaan ubah PIN terbaru yang JULO kirimkan ke kamu, ya!'
    )
    PIN_IS_WEAK = 'Jangan gunakan PIN yang mudah ditebak atau tanggal lahir sebagai PIN'


class VerifyPinTitle(object):
    GENERAL = 'Terjadi kesalahan'
    RESET_KEY_EXPIRED = 'Link Ubah PIN Sudah Kedaluwarsa'
    INVALID = 'Ubah PIN Gagal'
    INVALID_RESET_KEY = 'Terjadi kesalahan'


class PinResetReason(object):
    FROZEN = 'frozen reset'
    CORRECT_PIN = 'correct PIN reset'
    FORGET_PIN = 'forget PIN reset'


class ResetEmailStatus(object):
    SENT = 'Email Sent'
    CHANGED = 'PIN Changed'
    EXPIRED = 'Expired'
    REQUESTED = 'Requested'


class ResetPhoneNumberStatus(object):
    SENT = 'SMS Sent'
    CHANGED = 'PIN Changed'
    EXPIRED = 'Expired'
    REQUESTED = 'Requested'


class ReturnCode(object):
    OK = 'ok'
    UNAVAILABLE = 'unavailable'
    FAILED = 'failed'
    LOCKED = 'locked'
    PERMANENT_LOCKED = 'permanent_locked'


class OtpResponseMessage(object):
    FAILED = 'Permintaan OTP kamu tidak dapat kami proses, mohon coba lagi setelah beberapa saat'
    SUCCESS = 'Kode verifikasi sudah dikirim'


class ResetMessage:
    PASSWORD_RESPONSE = 'Email reset PIN/Kata Sandi akan dikirimkan ke email yang terdaftar'
    PIN_RESPONSE = 'Email reset PIN akan dikirimkan ke email yang terdaftar'
    RESET_PIN_BY_EMAIL = (
        'Periksa email kamu dan klik link untuk ' 'mengubah PIN/Kata Sandi akun JULO kamu'
    )
    RESET_PIN_BY_SMS = (
        'Periksa SMS kamu dan klik link untuk ' 'mengubah PIN/Kata Sandi akun JULO kamu'
    )
    FAILED = (
        'Permintaan Reset PIN/Kata Sandi kamu tidak dapat kami proses, mohon coba lagi'
        'setelah beberapa saat atau menghubungi customer service'
    )
    RESET_PIN_BY_EMAIL_V5 = "Kami sudah kirimkan email ke {masked_email} terkait permintaan ubah PIN kamu. \
                            Cek di semua folder email kamu, ya!"
    OUTDATED_OLD_VERSION = (
        "Fitur Ubah PIN hanya dapat diakses dengan aplikasi versi terbaru. Update JULO "
        "dulu, yuk! Untuk info lebih lanjut hubungi CS: \n\n"
        "Telepon: \n"
        "021-5091 9034/021-5091 9035 \n\n"
        "Email: \n"
        "cs@julo.co.id"
    )


class VerifySessionStatus:
    SUCCESS = 'success'
    FAILED = 'failed'
    REQUIRE_MULTILEVEL_SESSION_VERIFY = 'require_multilevel_session_verify'


class LoginFailMessage:
    MERCHANT_LOGIN_FAILURE_MSG_FOR_NON_MERCHANT = (
        'Login ke aplikasi JULO terlebih dahulu ' 'agar dapat melanjutkan transaksi'
    )


class PinErrors:
    KEY_INVALID = 1
    KEY_EXPIRED = 2
    BLANK_PIN = 3
    BAD_PIN_FORMAT = 4
    PINS_ARE_NOT_THE_SAME = 5
    PIN_IS_WEAK = 6
    PIN_IS_DOB = 7
    SAME_AS_OLD_PIN_RESET_PIN = 8
    INVALID_RESET_KEY = 9
    GENERAL = 10
    PREVIOUS_RESET_KEY = 11


class RegistrationType:
    PHONE_NUMBER = 'phone_number'


PIN_ERROR_MESSAGE_MAP = {
    PinErrors.KEY_INVALID: {'title': VerifyPinTitle.INVALID, 'message': VerifyPinMsg.INVALID},
    PinErrors.KEY_EXPIRED: {
        'title': VerifyPinTitle.RESET_KEY_EXPIRED,
        'message': VerifyPinMsg.RESET_KEY_EXPIRED,
    },
    PinErrors.BLANK_PIN: {'title': VerifyPinTitle.GENERAL, 'message': VerifyPinMsg.GENERAL},
    PinErrors.BAD_PIN_FORMAT: {'title': VerifyPinTitle.GENERAL, 'message': VerifyPinMsg.GENERAL},
    PinErrors.PINS_ARE_NOT_THE_SAME: {
        'title': VerifyPinTitle.GENERAL,
        'message': VerifyPinMsg.GENERAL,
    },
    PinErrors.PIN_IS_WEAK: {'title': VerifyPinTitle.GENERAL, 'message': VerifyPinMsg.GENERAL},
    PinErrors.PIN_IS_DOB: {'title': VerifyPinTitle.GENERAL, 'message': VerifyPinMsg.GENERAL},
    PinErrors.SAME_AS_OLD_PIN_RESET_PIN: {'message': VerifyPinMsg.SAME_AS_OLD_PIN},
    PinErrors.INVALID_RESET_KEY: {
        'title': VerifyPinTitle.INVALID_RESET_KEY,
        'message': VerifyPinMsg.INVALID_RESET_KEY,
    },
    PinErrors.GENERAL: {'title': VerifyPinTitle.GENERAL, 'message': VerifyPinMsg.GENERAL},
    PinErrors.PREVIOUS_RESET_KEY: {
        'title': VerifyPinTitle.RESET_KEY_EXPIRED,
        'message': VerifyPinMsg.PREVIOUS_RESET_KEY,
    },
}


JULOVER_PIN_ERROR_MESSAGE_MAP = {
    PinErrors.KEY_INVALID: VerifyPinMsg.JULOVER_RESET_KEY_INVALID,
    PinErrors.KEY_EXPIRED: VerifyPinMsg.JULOVER_RESET_KEY_INVALID,
    PinErrors.PIN_IS_DOB: VerifyPinMsg.JULOVER_WEAK_PIN,
    PinErrors.PIN_IS_WEAK: VerifyPinMsg.JULOVER_WEAK_PIN,
}


class CustomerResetCountConstants:
    MAXIMUM_NEW_PHONE_VALIDATION_RETRIES = 3
    CUSTOMER_NOT_EXISTS = 'customer tidak ditemukan'
    MAXIMUM_EXCEEDED = 'Permintaan ubah PIN udah mencapai batas maksimum. \
        Coba lagi di hari berikutnya, ya.'


class PersonalInformationFields:
    CUSTOMER_FIELDS = [
        'cdate',
        'udate',
        'nik',
        'dob',
        'mother_maiden_name',
        'email',
        'phone',
        'fullname',
    ]
    APPLICATION_FIELDS = [
        'cdate',
        'udate',
        'customer_mother_maiden_name',
        'loan_amount_request',
        'loan_duration_request',
        'dob',
        'birth_place',
        'ktp',
        'address_street_num',
        'address_provinsi',
        'address_kabupaten',
        'address_kecamatan',
        'address_kelurahan',
        'address_kodepos',
        'address_detail',
        'occupied_since',
        'home_status',
        'landlord_mobile_phone',
        'new_mobile_phone',
        'has_whatsapp_1',
        'mobile_phone_2',
        'has_whatsapp_2',
        'bbm_pin',
        'twitter_username',
        'instagram_username',
        'marital_status',
        'dependent',
        'spouse_name',
        'spouse_dob',
        "spouse_mobile_phone",
        "spouse_has_whatsapp",
        "kin_name",
        "kin_dob",
        "kin_gender",
        "kin_mobile_phone",
        "kin_relationship",
        "close_kin_name",
        "close_kin_mobile_phone",
        "close_kin_relationship",
        "job_type",
        "job_industry",
        "job_function",
        "job_description",
        "company_name",
        "company_phone_number",
        "work_kodepos",
        "job_start",
        "monthly_income",
        "income_1",
        "income_2",
        "income_3",
        "last_education",
        "college",
        "major",
        "graduation_year",
        "gpa",
        "has_other_income",
        "other_income_amount",
        "other_income_source",
        "monthly_housing_cost",
        "monthly_expenses",
        "total_current_debt",
        "vehicle_type_1",
        "vehicle_ownership_1",
        "bank_name",
        "bank_branch",
        "bank_account_number",
        "name_in_bank",
        "hrd_name",
        "company_address",
        "number_of_employees",
        "position_employees",
        "employment_status",
        "billing_office",
        "mutation",
        "dialect",
        "teaser_loan_amount",
        "additional_contact_1_name",
        "additional_contact_1_number",
        "additional_contact_2_name",
        "additional_contact_2_number",
        "loan_purpose_description_expanded",
        'email',
        'mobile_phone_1',
        'fullname',
        'have_facebook_data',
        'job_duration',
        'loan_purpose',
        'loan_purpose_desc',
        'payday',
        'address_same_as_ktp',
    ]


class MessageFormatPinConst:

    ADDITIONAL_MESSAGE_PIN_CLASSES = [
        'OTPCheckAllowed',
        'PreCheckPin',
    ]

    KEY_TIME_BLOCKED = 'time_blocked'
    KEY_IS_PERMANENT_BLOCK = 'is_permanent_block'
