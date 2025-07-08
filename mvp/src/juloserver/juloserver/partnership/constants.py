from builtins import object
from collections import namedtuple
from datetime import timedelta
from juloserver.julo.statuses import ApplicationStatusCodes

from enum import Enum

CSV_DELIMITER_SIZE = 1024
CARD_ID_METABASE_AXIATA_DISTRIBUTOR = 13716
MERCHANT_FINANCING_PREFIX = 'MF_'
PARTNERSHIP_CALLBACK_URL_STRING = 'api/partnership/callback/v1/'
Partnership_callback_mapping = namedtuple('Partnership_callback_mapping',
                                          ['list_code', 'mapping_status'])
partnership_status_mapping = namedtuple('partnership_status_mapping',
                                        ['list_code', 'mapping_status'])
MERCHANT_FINANCING_PREFIX = 'MF_'
DEFAULT_PARTNER_REDIRECT_URL = 'https://www.julo.co.id/'
SLACK_CHANNEL_LEADGEN_WEBVIEW_NOTIF = "C036WKND26S"
HTTP_422_UNPROCESSABLE_ENTITY = 422
PAYMENT_METHOD_NAME_BCA = 'Bank BCA'

INDONESIA = 'Indonesia'
AGENT_ASSISTED_PRE_CHECK_HEADERS = [
    "name",
    "nik",
    "email",
    "phone",
    "loan_purpose",
    "agent_code",
    "partner_name",
    "application_xid",
    "is_pass",
    "notes",
]
AGENT_ASSISTED_FDC_PRE_CHECK_HEADERS = [
    "application_xid",
    "gender",
    "dob",
    "birth_place",
    "address_street_num",
    "address_kabupaten",
    "address_kecamatan",
    "address_kelurahan",
    "address_kodepos",
    "address_provinsi",
    "nik",
    "email",
    "phone",
    "name",
    "partner_name",
    "is_pass",
    "notes",
]
PRE_CHECK_SUFFIX_EMAIL = "julotemp@julopartner.com"
PRE_CHECK_IDENTIFIER = 900
AGENT_ASSISTED_UPLOAD_USER_DATA_HEADERS = [
    "application_xid",
    "email",
    "ktp",
    "dob",
    "gender",
    "address_provinsi",
    "occupied_since",
    "home_status",
    "dependent",
    "mobile_phone_1",
    "job_type",
    "job_industry",
    "job_description",
    "job_start",
    "payday",
    "last_education",
    "monthly_income",
    "monthly_expenses",
    "monthly_housing_cost",
    "total_current_debt",
    "is_pass",
    "notes",
]


AGENT_ASSISTED_COMPLETE_DATA_STATUS_UPDATE_HEADERS = [
    "application_xid",
    "email",
    "mobile_phone_1",
    "birth_place",
    "mother_maiden_name",
    "address_street_num",
    "address_kabupaten",
    "address_kecamatan",
    "address_kelurahan",
    "address_kodepos",
    "marital_status",
    "close_kin_name",
    "close_kin_mobile_phone",
    "spouse_name",
    "spouse_mobile_phone",
    "kin_relationship",
    "kin_name",
    "kin_mobile_phone",
    "company_name",
    "company_phone_number",
    "bank_name",
    "bank_account_number",
    "ktp_photo",
    "selfie_photo",
    "photo_of_income_proof",
    "is_pass",
    "notes",
]
MAP_PAYMENT_FREQUENCY = {
    1: 'daily',
    7: 'weekly',
    14: 'biweekly',
    30: 'monthly',
}
LOAN_DURATION_UNIT_DAY = "day"


class AddressConst(object):
    PROVINCE = 'province'
    CITY = 'city'
    DISTRICT = 'district'
    SUB_DISTRICT = 'sub_district'

    HOME_STATUS_CHOICES = (
        ('Kontrak', 'Kontrak'),
        ('Kos', 'Kos'),
        ('Milik orang tua', 'Milik orang tua'),
        ('Milik keluarga', 'Milik keluarga'),
        ('Milik sendiri, lunas', 'Milik sendiri, lunas'),
        ('Milik sendiri, mencicil', 'Milik sendiri, mencicil'))

    @classmethod
    def all_address(cls):
        return [cls.PROVINCE, cls.CITY, cls.DISTRICT, cls.SUB_DISTRICT]


class ErrorMessageConst(object):
    INVALID_DATA = 'data tidak valid'
    INVALID_PATTERN = 'tidak memenuhi pattern yang dibutuhkan'
    REQUIRED = 'tidak boleh kosong'
    SPACE_MORE_THAN_ONE = 'tidak boleh double spasi'
    REAL_NAME = 'mohon gunakan nama asli'
    FORMAT_PHONE_NUMBER = 'mohon isi dengan format 08xxxxx dan '\
                          'harus terdiri dari 10 sampai 14 digit angka'
    FORMAT_MERCHANT_PHONE_NUMBER = 'mohon isi dengan format 08xxxxx atau 02xxxxx dan ' \
                                   'harus terdiri dari 10 sampai 14 digit angka'
    FORMAT_COMPANY_PHONE_NUMBER = 'mohon diisi dengan format 021xxxxx atau dengan '\
                                  'nomor daerah lainnya minimal 9 digit'
    NUMERIC = 'harus angka'
    REGISTERED = 'Anda sudah terdaftar'
    NOT_FOUND = 'tidak ditemukan'
    INVALID_DATE = 'Format tanggal tidak sesuai, seharusnya: YYYY-MM-DD'
    NOT_TRUE = 'harus true'
    NOT_BOOLEAN = 'harus boolean'
    PHONE_NUMBER_REGISTERED = 'nomor hp sudah terdaftar'
    PHONE_NUMBER_CANT_BE_SAME = 'Phone number tidak boleh sama'
    EMAIL_SHOULD_GOOGLE = 'Email harus google'
    GENERAL_ERROR = 'Ada kesalahan dalam data Anda. Mohon dicek dan disubmit kembali'
    APPLICATION_STATUS_NOT_VALID = 'Aplikasi status tidak valid'
    OTP_NOT_VERIFIED = 'harus verifikasi otp terlebih dahulu'
    IMAGE_NOT_UPLOAD = 'upload images ktp_self, crop_selfie dan selfie terlebih dahulu'
    MERCHANT_NOT_REGISTERED = 'merchant tidak terdaftar'
    MERCHANT_REGISTERED = 'merchant sudah terdaftar'
    INVALID_FORMAT = 'tidak memenuhi format yang dibutuhkan'
    NEGATIVE_NUMBER = 'tidak menerima digit negatif'
    NOT_PARTNER = 'pengguna ini belum terdaftar sebagai partner JULO'
    INVALID_PARTNER = 'partner tidak valid'
    APPLIED_APPLICATION = "Anda sudah melakukan pengajuan beberapa waktu lalu. " \
                          "Silakan melakukan pengajuan ulang melalui " \
                          "aplikasi JULO."
    CANT_ACCESS_RENTEE = 'Akun ini tidak dapat mengakses rentee'
    SIGNATURE_NOT_UPLOADED = 'tanda tangan belum diunggah'
    NOT_ALLOWED = 'akses tidak diperbolehkan'
    SPHP_UPLOADED = 'SPHP sudah diupload'
    INVALID_TOKEN = 'token tidak valid'
    SPHP_EXPIRED = 'link SPHP sudah kadaluarsa'
    ACCOUNT_NOT_LINKED = 'Akun belum terhubung dengan partner yang bersangkutan'
    PARTNER_REFERENCE_NOT_MATCHED = "partner reference id tidak ditemukan"
    NOT_ACTIVE_USER = 'user tidak aktif'
    INVALID_CREDENTIALS = 'kredensial tidak valid'
    LOWER_THAN_MIN_THRESHOLD = 'Kamu belum dapat mengajukan pinjaman'
    LOWER_THAN_MAX_THRESHOLD_LINKAJA = 'Batas maksimum penarikan dana Rp10.000.000'
    INVALID_LOAN_REQUEST_AMOUNT = 'Jumlah yang kamu masukkan salah, periksa kembali'
    OVER_LIMIT = 'Limit kamu tidak mencukupi untuk pinjaman ini'
    STATUS_NOT_VALID = 'akun belum dapat mengajukan loan'
    IN_PROGRESS_UPLOAD = 'Upload sebelumnya sedang berjalan'
    THREE_TIMES_UPLOADED = 'Sudah melakukan upload sebanyak 3 kali untuk aplikasi ini'
    SHOULD_BE_FILLED = 'Harus Diisi'
    FORMAT_PHONE_NUMBER_PARTNERSHIP = 'format tidak sesuai'
    STATUS_NOT_VALID = 'akun belum dapat mengajukan loan'
    INVALID_CUSTOMER = 'customer tidak valid'
    INVALID_NIK_OR_PASSWORD = 'NIK, PIN atau Kata Sandi Anda salah'
    RECHECK_YOUR_PIN = 'Periksa kembali PIN Anda'
    DATA_NOT_FOUND = 'Data tidak ditemukan'
    LOAN_NOT_FOUND = 'Loan tidak ditemukan'
    INVALID_STATUS = 'Maaf, Anda belum dapat melanjutkan proses'
    TOO_MANY_REQUESTS = 'Terlalu banyak melakukan permintaan'
    INVALID_DATA_CHECK = 'Data tidak valid, mohon cek kembali'
    EMAIL_OR_PHONE_NOT_FOUND = 'Email/Nomor Handphone tidak sesuai'
    INVALID_PAYLATER_TRANSACTION_XID = 'paylater_transaction_xid tidak valid'
    PAYLATER_TRANSACTION_XID_NOT_FOUND = 'paylater_transaction_xid tidak ditemukan'
    PRODUCT_NOT_FOUND = 'products wajib diisi'
    APPLICATION_NOT_FOUND = 'Application tidak ditemukan'
    FORMAT_EMAIL_INVALID = 'Email tidak valid'
    ACCOUNT_NOT_FOUND = 'Akun tidak ditemukan'
    PAYLATER_TRANSACTION_STATUS_NOT_FOUND = "Invalid data, paylater transaction status not found"
    PARTNER_ORIGIN_NAME_NOT_FOUND = 'partner_origin_name tidak ditemukan'
    CUSTOMER_NOT_FOUND = "Customer tidak ditemukan"
    CUSTOMER_HAS_REGISTERED = "Kamu sudah terdaftar di JULO, " \
        "silahkan login menggunakan aplikasi JULO kamu"
    INVALID_LOGIN = 'Kamu tidak dapat melanjutkan transaksi, masuk ke akun kamu melalui aplikasi ' \
                    'JULO untuk informasi lebih detail'
    CONTACT_CS_JULO = 'Kamu dapat menghubungi CS JULO untuk melanjutkan proses ini'
    CONCURRENCY_MESSAGE_CONTENT = (
        'Untuk sementara Anda hanya bisa memiliki 1 (satu) pinjaman aktif.'
    )
    PHONE_INVALID = 'Format penulisan nomor HP harus sesuai. Contoh: 08123456789'
    LOGIN_ATTEMP_FAILED_PARTNERSHIP = (
        'Kamu telah {attempt_count} kali salah memasukkan informasi. '
        + '{max_attempt} kali salah akan memblokir sementara akun milikmu.'
    )
    INCORRECT_PIN = 'PIN tidak sesuai, coba kembali'
    INVALID_PRODUCT = 'product tidak valid'
    INVALID_SUBMISSION_APPLICATION = 'Gagal submit aplikasi'
    REQUIRED_INT_FORMAT = "Harus ditulis dalam bilangan bulat"
    MAXIMUM_DIGIT_NUMBER = "Maks. {} digit"
    MINIMUN_DIGIT_NUMBER = "Min. {} digit"
    MAXIMUM_CHARACTER = "Tidak lebih dari maks. {} karakter"
    MINIMUN_CHARACTER = "Min. {} karakter"
    INVALID_NAME = "Mohon pastikan nama sesuai format (tanpa Bpk, Ibu, Sdr, dsb)"
    INVALID_DOUBLE_SPACE = 'Harap diisi tanpa dobel spasi'
    REQUIRE_LETTERS_ONLY = 'Harap diisi dengan huruf saja'
    INVALID_NIK_NOT_REGISTERED = "NIK tidak terdaftar"
    WRONG_FORMAT = "Format tidak sesuai"
    INVALID_DATE_FORMAT = "Mohon masukkan tanggal lahir yang benar, ya"
    INVALID_REQUIRED = "harus diisi dengan benar"
    INVALID_DUPLICATE_WITH_PRIMAY_PHONE_NUMBER = "Nomor HP tidak boleh sama dengan pemilik akun"
    INVALID_DUPLICATE_OTHER_PHONE_NUMBER = (
        "Nomor HP tidak boleh sama dengan yang sudah dimasukkan sebelumnya"
    )
    INVALID_DUPLICATE_COMPANY_PHONE_NUMBER = (
        "Nomor tidak boleh sama dengan yang sudah dimasukkan sebelumnya"
    )
    INVALID_BANK_ACCOUNT_NUMBER = "Pastikan nomor rekening kamu benar"
    INVALID_FORMAT_DATA = "Harap diisi dengan format yang sesuai"


class JobsConst(object):
    IBU_RUMAH_TANGGA = 'Ibu rumah tangga'
    STAF_RUMAH_TANGGA = 'Staf rumah tangga'
    TIDAK_BEKERJA = 'Tidak bekerja'
    MAHASISWA = 'Mahasiswa'
    JOBLESS_CATEGORIES = {TIDAK_BEKERJA, STAF_RUMAH_TANGGA, IBU_RUMAH_TANGGA, MAHASISWA}


Partnership_callback_mapping_statuses = (
    Partnership_callback_mapping(
        list_code=[105],
        mapping_status="CREDIT_SCORE_GENERATED"
    ),
    Partnership_callback_mapping(
        list_code=[121],
        mapping_status="DOCUMENT_VERIFICATION"
    ),
    Partnership_callback_mapping(
        list_code=[122, 124],
        mapping_status="PHONE_VERIFICATION"
    ),
    Partnership_callback_mapping(
        list_code=[131],
        mapping_status="REUPLOAD_DOCUMENT"
    ),
    Partnership_callback_mapping(
        list_code=[141],
        mapping_status="LIMIT_GENERATED"
    ),
    Partnership_callback_mapping(
        list_code=[150],
        mapping_status="PRIVY_REGISTRATION"
    ),
    Partnership_callback_mapping(
        list_code=[190],
        mapping_status="LIMIT_READY_TO_USE"
    ),
    Partnership_callback_mapping(
        list_code=[106, 133, 135, 137, 139, 142],
        mapping_status="GRAVEYARD_STATUS"
    ),
)


partnership_status_mapping_statuses = (
    partnership_status_mapping(
        list_code=0,
        mapping_status="FORM_NOT_CREATED"
    ),
    partnership_status_mapping(
        list_code=100,
        mapping_status="FORM_CREATED"
    ),
    partnership_status_mapping(
        list_code=105,
        mapping_status="FORM_SUBMITTED"
    ),
    partnership_status_mapping(
        list_code=1051,
        mapping_status="MERCHANT_HISTORICAL_TRANSACTION_INVALID"
    ),
    partnership_status_mapping(
        list_code=106,
        mapping_status="FORM_EXPIRED"
    ),
    partnership_status_mapping(
        list_code=120,
        mapping_status="DOCUMENTS_SUBMITTED"
    ),
    partnership_status_mapping(
        list_code=121,
        mapping_status="SCRAPPED_DATA_VERIFIED"
    ),
    partnership_status_mapping(
        list_code=122,
        mapping_status="DOCUMENTS_VERIFIED"
    ),
    partnership_status_mapping(
        list_code=124,
        mapping_status="VERIFICATION_CALL_ONGOING"
    ),
    partnership_status_mapping(
        list_code=125,
        mapping_status="CALL_ASSESMENT"
    ),
    partnership_status_mapping(
        list_code=130,
        mapping_status="LIMIT_GENERATED"
    ),
    partnership_status_mapping(
        list_code=131,
        mapping_status="RESUBMISSION_APPLICATION_REQUESTED"
    ),
    partnership_status_mapping(
        list_code=132,
        mapping_status="APPLICATION_RESUBMITTED"
    ),
    partnership_status_mapping(
        list_code=133,
        mapping_status="APPLICATION_FRAUD"
    ),
    partnership_status_mapping(
        list_code=135,
        mapping_status="APPLICATION_REJECTED"
    ),
    partnership_status_mapping(
        list_code=137,
        mapping_status="APPLICATION_CANCELLED_BY_CUSTOMER"
    ),
    partnership_status_mapping(
        list_code=139,
        mapping_status="APPLICATION_EXPIRED"
    ),
    partnership_status_mapping(
        list_code=141,
        mapping_status="LIMIT_ACTIVATION"
    ),
    partnership_status_mapping(
        list_code=142,
        mapping_status="LIMIT_ACTIVATION_REJECTED"
    ),
    partnership_status_mapping(
        list_code=145,
        mapping_status="DIGISIGN_FAILED"
    ),
    partnership_status_mapping(
        list_code=147,
        mapping_status="DIGISIGN_IMAGE_RESUBMISSION"
    ),
    partnership_status_mapping(
        list_code=150,
        mapping_status="LIMIT_ACTIVATION_SUCCESS"
    ),
    partnership_status_mapping(
        list_code=160,
        mapping_status="SPHP_SIGNING"
    ),
    partnership_status_mapping(
        list_code=190,
        mapping_status="LIMIT_READY_TO_USE"
    ),
    partnership_status_mapping(
        list_code=210,
        mapping_status="LOAN_CREATED"
    ),
    partnership_status_mapping(
        list_code=211,
        mapping_status="LOAN_WAITING_FOR_APPROVAL"
    ),
    partnership_status_mapping(
        list_code=212,
        mapping_status="LOAN_DISBURSAL_ON_PROCESS"
    ),
    partnership_status_mapping(
        list_code=213,
        mapping_status="MANUAL_DISBURSAL"
    ),
    partnership_status_mapping(
        list_code=216,
        mapping_status="LOAN_CANCELLED_BY_CUSTOMER"
    ),
    partnership_status_mapping(
        list_code=217,
        mapping_status="LOAN_EXPIRED"
    ),
    partnership_status_mapping(
        list_code=218,
        mapping_status="LOAN_DISBURSAL_FAILED"
    ),
    partnership_status_mapping(
        list_code=220,
        mapping_status="LOAN_DISBURSAL_SUCCESS"
    ),
    partnership_status_mapping(
        list_code=230,
        mapping_status="LOAN_1_DPD"
    ),
    partnership_status_mapping(
        list_code=231,
        mapping_status="LOAN_5_DPD"
    ),
    partnership_status_mapping(
        list_code=232,
        mapping_status="LOAN_30_DPD"
    ),
    partnership_status_mapping(
        list_code=233,
        mapping_status="LOAN_60_DPD"
    ),
    partnership_status_mapping(
        list_code=234,
        mapping_status="LOAN_90_DPD"
    ),
    partnership_status_mapping(
        list_code=235,
        mapping_status="LOAN_120_DPD"
    ),
    partnership_status_mapping(
        list_code=236,
        mapping_status="LOAN_150_DPD"
    ),
    partnership_status_mapping(
        list_code=237,
        mapping_status="LOAN_180_DPD"
    ),
    partnership_status_mapping(
        list_code=250,
        mapping_status="LOAN_PAID_OFF"
    ),
)


class PartnershipTypeConstant(object):
    LEAD_GEN = 'Lead gen'
    MERCHANT_FINANCING = 'Merchant financing'
    WHITELABEL_PAYLATER = 'Whitelabel Paylater'
    IPRICE = 'iprice'
    MOCK = 'mock'
    JULOSHOP = 'juloshop'
    LEADGEN_WEBVIEW = 'Leadgen Webiew'


class WhitelabelURLPaths(object):
    TNC_PAGE = 'view/activation/tnc?auth={secret_key}&redirect_url={redirect_url}'
    DATA_COMFIRMATION_PAGE = 'view/activation/data-confirmation?' \
                             'auth={secret_key}&redirect_url={redirect_url}'
    ERROR_PAGE = 'view/activation/error?errorType={error_type}&redirect_url={redirect_url}'
    INPUT_PIN = 'input-pin/{xid}'
    VERIFY_PAGE = 'view/activation/verify-page?' \
                  'auth={secret_key}&errorType={error_type}&redirect_url={redirect_url}'


class WhitelabelErrorType(object):
    UNREGISTERED = 'unregistered'
    VERIFICATION_IN_PROGRESS = 'verification+on+process'
    SYSTEM_ERROR = 'activation+system+error'
    VERIFY = 'verify'


class AgreementStatus(object):
    SIGN = 'sign'
    CANCEL = 'cancel'


WHITELABEL_PAYLATER_REGEX = r"^\S+@\S+\.\S+:(628)\d{8,11}:[a-zA-Z0-9_-]{2,}:[\S+]{2,}:(.*)$"
PAYLATER_REGEX = r"^\S+@\S+\.\S+:(08)\d{8,12}:[a-zA-Z0-9_-]{2,}:[\S+]{2,}:[\S+]{2,}:[0-9]{2,}$"


class HTTPStatusCode(object):
    EXCLUDE_FROM_SENTRY = {
        400, 401, 403, 405, 404
    }


class LoanPartnershipConstant(object):
    MIN_LOAN_AMOUNT_THRESHOLD = 300000
    MAX_LOAN_AMOUNT_THRESHOLD_LINKAJA = 10000000
    PHONE_NUMBER_BLACKLIST = 'phone_number_blacklist'


class InvalidBankAccountAndTransactionType(object):
    INVALID_BANK_ACCOUNT_AND_TRANSACTION_TYPE = {
        'Kombinasi': 'self_bank_account dan transaction_type_code salah'
    }


class PartnershipRedisPrefixKey(object):
    WEBVIEW_CREATE_LOAN = 'webview_create_loan'
    WEBVIEW_GET_PHONE_NUMBER = 'webview_get_phone_number'
    WEBVIEW_DISBURSEMENT = 'webview_disbursement'
    WEBVIEW_CHECK_TRANSACTION = 'webview_check_transaction'
    LEADGEN_RESET_PIN_EMAIL = 'leadgen_reset_pin_email'
    LEADGEN_PRODUCT_LIST = 'leadgen_product_list'


class LinkajaPages(object):
    LOAN_EXPECTATION_PAGE = 'loan_expectation_page'
    LONG_FORM_PAGE = 'long_form_page'
    REGISTRATION_PAGE = 'registration_page'
    PIN_CREATION_PAGE = 'pin_creation_page'
    J1_VERIFiCATION_PAGE = 'j1_verification_page'
    REJECT_DUE_TO_NON_J1_CUSTOMER = 'non_j1_customer_page'


j1_reapply_status = {
    ApplicationStatusCodes.FORM_PARTIAL_EXPIRED,
    ApplicationStatusCodes.APPLICATION_DENIED,
    ApplicationStatusCodes.FORM_SUBMISSION_ABANDONED,
    ApplicationStatusCodes.RESUBMISSION_REQUEST_ABANDONED,
    ApplicationStatusCodes.APPLICATION_CANCELED_BY_CUSTOMER,
    ApplicationStatusCodes.VERIFICATION_CALLS_EXPIRED,
}


class PartnershipChangeReason(object):
    DISBURSEMENT_FAILED_ON_PARTNER_SIDE = 'Disbursement failed on partner side'


class PartnershipLogStatus(object):
    IN_PROGRESS = 'in_progress'
    SUCCESS = 'success'
    FAILED = 'failed'


class PaylaterTransactionStatuses(object):
    """
        initiate =  when hit /v1/transaction-details API
        in_progress =  pin or linking success
        success =  loan creation done
        cancel = cancel within 7 or 9 days etc.
    """
    INITIATE = 'initiate'
    IN_PROGRESS = 'in_progress'
    SUCCESS = 'success'
    CANCEL = 'cancel'


class PaylaterURLPaths(object):
    LOGIN_PAGE = 'paylater/login?auth={secret_key}'
    ERROR_PAGE = 'paylater/not-match?auth={secret_key}'
    VERIFY_OTP = 'paylater/otp?auth={secret_key}'
    ACTIVATION_PAGE = 'paylater/activation?auth={secret_key}'
    PAYMENT_PAGE = 'paylater/transactions?auth={secret_key}'


class PartnershipEmailHistory(object):
    PENDING = 'pending'
    DELIVERED = 'delivered'


class APISourceFrom(object):
    INTERNAL = "internal"
    EXTERNAL = "external"


class GenderChoices(object):
    MALE = 'male'
    FEMALE = 'female'


class MarriageStatus(object):
    MARRIED = 'married'
    NOT_MARRIED = 'not_married'


class EFWebFormType(object):
    APPLICATION = 'application'
    DISBURSEMENT = 'disbursement'
    MASTER_AGREEMENT = 'master_agreement'


class PhoneNumberFormat(object):
    E164 = 0  # Example: +6281232132132
    INTERNATIONAL = 1  # Example: +62 812-3213-2132
    NATIONAL = 2  # Example: 0812-3213-2132
    RFC3966 = 3  # Example: tel:+62-812-3213-2132
    # Beside above format Example: 812-3213-2132


class PartnershipImageStatus(object):
    INACTIVE = -1
    ACTIVE = 0
    RESUBMISSION_REQ = 1


class PartnershipImageType(object):
    KTP_SELF = "ktp_self"
    SELFIE = "selfie"
    CROP_SELFIE = "crop_selfie"
    BANK_STATEMENT = "bank_statement"
    PAYSTUB = "paystub"
    PAYSTUB_OPS = "paystub_ops"
    KTP_SELF_OPS = "ktp_self_ops"
    SELFIE_OPS = "selfie_ops"


class PartnershipImageService(object):
    S3 = 's3'
    OSS = 'oss'


class PartnershipImageProductType(object):
    PARTNERSHIP_DEFAULT = "partnership"
    MF_CSV_UPLOAD = "merchant_financing_csv_upload"
    EMPLOYEE_FINANCING = "employee_financing"
    PAYLATER = "paylater"
    LEADGEN = "leadgen"
    MF_API = "merchant_financing_api"
    GRAB = "grab"
    DANA = "dana"
    AXIATA = "Axiata"


class PartnershipLoanStatusChangeReason(object):
    DIGITAL_SIGNATURE_SUCCEED = "Digital signature succeed"
    LOAN_APPROVED_BY_LENDER = "Loan approved by lender"
    ACTIVATED = "Loan activated"
    SETTLEMENT_CANCELED = "Loan canceled from settlement file"
    INVALID_LOAN_STATUS = "Current Loan Status is Invalid"
    LOAN_REJECTED_BY_LENDER = "Loan rejected by lender"
    LOAN_CANCELLED_BY_MAX_3_PLATFORM = "Cancelled due to active loan on 3 other platform"
    MANUAL_DISBURSEMENT = "Manual disbursement on process"


IMAGE_EXTENSION_FORMAT = {'png', 'jpg', 'jpeg', 'webp', 'tiff', 'tif', 'bmp'}


class PartnershipLender(object):
    JTP = "jtp"
    IAF_JTP = 'iaf_jtp'


class PartnershipDisbursementType(object):
    LOAN = "loan"


class SPHPOutputType:
    WEBVIEW = "webview"
    AXIATA = "axiata"


class PartnershipAccountLookup:
    DANA = "DANA"
    MERCHANT_FINANCING = "Partnership Merchant Financing"


class PaylaterUserAction(object):
    CHECKOUT_INITIATED = "checkout initiated"
    CREATING_PIN = "creating pin"
    LONG_FORM_APPLICATION = "long form application"
    APPLICATION_SUBMISSION = "application submission"
    ONLY_EMAIL_AND_PHONE_MATCH = "only email/phone number match"
    TOGGLE_SWITCHED_ON = "toggle switched on"
    TOGGLE_SWITCHED_OFF = "toggle switched off"
    LOGIN_SCREEN = "login screen"
    VERIFY_OTP = "verify otp"
    LINKING_COMPLETED = "linking completed"
    INSUFFICIENT_BALANCE = "insufficient balance"
    SELECT_DURATION = "select duration"
    TRANSACTION_SUMMARY = "transaction summary"
    SUCCESSFUL_TRANSACTION = "successful transaction"
    CANCELLED_TRANSACTION = "cancelled transaction"


class PartnershipTokenType:
    ACCESS_TOKEN = "access_token"
    REFRESH_TOKEN = "refresh_token"
    LIFETIME = "lifetime"
    OTP_LOGIN_VERIFICATION = "otp_login_verification"
    RESET_PIN_TOKEN = "reset_pin_token"
    OTP_REGISTER_VERIFICATION = "otp_register_verification"
    CHANGE_PIN = "change_pin"


DOCUMENT_EXTENSION_FORMAT = {'.csv', '.xls', '.xlsx', '.doc', '.docx', '.pdf'}
UPLOAD_DOCUMENT_MAX_SIZE = 1024 * 1024 * 2
DOCUMENT_TYPE = {
    'nib_document',
    'financial_document',
    'cashflow_report',
    'other_document',
    'company_photo',
    'credit_memo',
    'slik',
    'sales_report',
}
IMAGE_EXTENSION_FORMAT = {'.jpeg', '.png', '.jpg', '.webp', '.bmp'}
IMAGE_TYPE = {'ktp', 'selfie', 'company_photo', 'crop_selfie', 'kk'}


class HashidsConstant:
    MIN_LENGTH = 16


class JWTLifetime(Enum):
    ACCESS = timedelta(days=1)
    REFRESH = timedelta(days=1)
    RESET_PIN = timedelta(hours=2)


class HTTPGeneralErrorMessage(object):
    INTERNAL_SERVER_ERROR = 'Kesalahan server internal.'
    UNAUTHORIZED = 'Autentikasi tidak valid atau tidak ditemukan.'
    INVALID_REQUEST = 'Permintaan tidak valid.'
    HTTP_METHOD_NOT_ALLOWED = 'Metode Tidak Diizinkan.'
    PAGE_NOT_FOUND = 'Halaman tidak ditemukan.'
    FORBIDDEN_ACCESS = 'Akses tidak diizinkan.'
    INVALID_APPLICATION = 'Application tidak valid'


class ResponseErrorMessage:
    FIELD_REQUIRED = "Kolom ini harus diisi"
    INVALID_NIK = "Harus berupa angka dan 16 digit"
    INVALID_PIN = "Harus berupa angka dan 6 digit"
    INVALID_PIN_WEAK = "PIN terlalu lemah"
    INVALID_PIN_DOB = "PIN tidak boleh sama dengan tanggal lahirmu"
    DATA_NOT_FOUND = "Data tidak ditemukan"


class PartnershipMaritalStatusConst(object):
    MENIKAH = "Menikah"
    LAJANG = "Lajang"
    CERAI = "Cerai"
    JANDA_DUDA = "Janda / duda"
    LIST_MARITAL_STATUS = {MENIKAH, LAJANG, CERAI, JANDA_DUDA}


class PartnershipHttpStatusCode:
    HTTP_422_UNPROCESSABLE_ENTITY = 422
    HTTP_207_MULTI_STATUS = 207
    HTTP_425_TOO_EARLY = 425


class LoanDurationType:
    DAYS = 'days'
    MONTH = 'month'
    WEEKLY = 'weekly'
    BIWEEKLY = 'biweekly'


class LoanPurposeType:
    MODAL_USAHA = 'Modal Usaha'


class PartnershipPreCheckFlag(object):
    PASSED_PRE_CHECK = "passed_pre_check"
    NOT_PASSED_PRE_CHECK = "not_passed_pre_check"
    PASSED_FDC_PRE_CHECK = "passed_fdc_pre_check"
    NOT_PASSED_FDC_PRE_CHECK = "not_passed_fdc_pre_check"
    PASSED_BINARY_PRE_CHECK = "passed_binary_pre_check"
    NOT_PASSED_BINARY_PRE_CHECK = "not_passed_binary_pre_check"
    EXPIRED_APPLICATION_REFERENCE = "expired_application_reference"
    REGISTER_FROM_PORTAL = "register_from_portal"
    PENDING_CREDIT_SCORE_GENERATION = "pending_credit_score_generation"
    ELIGIBLE_TO_BINARY_PRE_CHECK = "eligible_to_binary_pre_check"
    NOT_ELIGIBLE_TO_BINARY_PRE_CHECK = "not_eligible_to_binary_pre_check"
    PASSED_TELCO_PRE_CHECK = "passed_telco_pre_check"
    NOT_PASSED_TELCO_PRE_CHECK = "not_passed_telco_pre_check"
    PASSED_CLIK_PRE_CHECK = "passed_clik_pre_check"
    NOT_PASSED_CLIK_PRE_CHECK = "not_passed_clik_pre_check"
    APPROVED = 'approved'


class PartnershipRejectReason(object):
    BLACKLISTED = 'blacklist_customer_check'
    FRAUD = 'other_fraud_suspicions'
    DELINQUENT = 'prev_delinquency_check'


class PartnershipProductFlow(object):
    AGENT_ASSISTED = "agent_assisted"
    LEADGEN = "leadgen"
    EMPLOYEE_FINANCING = "employee_financing"


class AgentAssistedUploadType:
    PRE_CHECK_APPLICATION = 'pre_check_application'
    SCORING_DATA_UPLOAD = 'scoring_data_upload'
    FDC_PRE_CHECK_APPLICATION = 'fdc_pre_check_application'
    COMPLETE_USER_DATA_STATUS_UPDATE_UPLOAD = 'complete_user_data_status_update_upload'


JOB_TYPE = {
    'Pengusaha',
    'Freelance',
    'Staf rumah tangga',
    'Pekerja rumah tangga',
    'Ibu rumah tangga',
    'Mahasiswa',
    'Tidak bekerja',
    'Pegawai swasta',
    'Pegawai negeri',
}

JOB_INDUSTRY = {
    'Sales / Marketing',
    'Pabrik / Gudang',
    'Service',
    'Pendidikan',
    'Transportasi',
    'Konstruksi / Real Estate',
    'Perawatan Tubuh',
    'Admin / Finance / HR',
    'Perbankan',
    'Kesehatan',
    'Tehnik / Computer',
    'Hukum / Security / Politik',
    'Perhotelan',
    'Entertainment / Event',
    'Design / Seni',
    'Staf Rumah Tangga',
    'Teknologi Informasi',
    'Perdagangan',
    'Media',
}

JOB_DESC = {
    'SPG',
    'Buruh Pabrik / Gudang',
    'Kebersihan',
    'Lainnya',
    'Guru',
    'Supir / Ojek',
    'Kasir',
    'Kurir / Ekspedisi',
    'Pemborong',
    'Kepala Pabrik / Gudang',
    'Sewa Kendaraan',
    'Salon / Spa / Panti Pijat',
    'Admin',
    'Back-office',
    'Telemarketing',
    'Account Executive / Manager',
    'Teknisi Mesin',
    'Satpam',
    'Perawat',
    'Mandor',
    'Salesman',
    'Dosen',
    'Engineer / Ahli Tehnik',
    'Proyek Manager / Surveyor',
    'Kepala Sekolah',
    'Arsitek / Tehnik Sipil',
    'Akuntan / Finance',
    'Koki',
    'Programmer / Developer',
    'Design Grafis',
    'Customer Service',
    'Real Estate Broker',
    'Photographer',
    'Apoteker',
    'Dokter',
    'Office Boy',
    'R&D / Ilmuwan / Peneliti',
    'Room Service / Pelayan',
    'Pelayan / Pramuniaga',
    'Tukang Bangunan',
    'Babysitter / Perawat',
    'Pelaut / Staff Kapal / Nahkoda Kapal',
    'Sekretaris',
    'Event Organizer',
    'Pembantu Rumah Tangga',
    'Otomotif',
    'Penulis Teknikal',
    'Teknisi Laboratorium',
    'Instruktur / Pembimbing Kursus',
    'Produser / Sutradara',
    'HR',
    'Tata Usaha',
    'CS Bank',
    'Penyanyi / Penari / Model',
    'Notaris',
    'Agen Perjalanan',
    'Interior Designer',
    'Fashion Designer',
    'Warnet',
    'Kameraman',
    'Supir',
    'Pilot / Staff Penerbangan',
    'DJ / Musisi',
    'Tukang Kebun',
    'Masinis / Kereta Api',
    'Gym / Fitness',
    'Bank Teller',
    'Pelukis',
    'Pelatih / Trainer',
    'Resepsionis',
    'Accounting',
    'Penulis / Editor',
    'Anggota Pemerintahan',
    'Kolektor',
    'Head Office',
    'Credit Analyst',
}


class PartnershipFlag(object):
    FIELD_CONFIGURATION = "field_configuration"
    MAX_CREDITOR_CHECK = "max_creditor_check"
    DANA_FDC_LIMIT_APPLICATION_HANDLER = 'dana_fdc_limit_application_handler'
    DANA_COUNTDOWN_PROCESS_NOTIFY_CONFIG = 'dana_countdown_process_notify_config'
    DISBURSEMENT_CONFIGURATION = 'disbursement_configuration'
    CLIK_INTEGRATION = "clik_integration"
    # this will cover application with partner referral code or partner onelink
    FORCE_FILLED_PARTNER_ID = "force_filled_partner_id"
    PAYMENT_GATEWAY_SERVICE = "payment_gateway_service"
    APPROVAL_CONFIG = "approval_config"
    LEADGEN_PARTNER_CONFIG = 'leadgen_partner_config'
    LEADGEN_SUB_CONFIG_LOCATION = "leadgen_sub_config_location"
    LEADGEN_SUB_CONFIG_LONG_FORM = "leadgen_sub_config_long_form"
    LEADGEN_SUB_CONFIG_LOGO = "leadgen_sub_config_logo"


class PartnershipUploadImageDestination(object):
    PARNTERSHIP_IMAGE_TABLE = 'partnership_image_table'
    IMAGE_TABLE = 'image_table'


class AgentAssistedEmailFlowConfig(object):
    APPROVED_AGENT_ASSISTED_EMAIL = "approved_agent_assisted_email"
    REJECT_AGENT_ASSISTED_EMAIL = "reject_agent_assisted_email"
    REJECT_C_SCORE_AGENT_ASSISTED_EMAIL = "reject_c_score_agent_assisted_email"
    FORM_SUBMITTED_AGENT_ASSISTED_EMAIL = "form_submitted_agent_assisted_email"
    SKIP_PIN_CREATION_AGENT_ASSISTED_EMAIL = "skip_uw_application_email_pin_creation"
    TELCO_SCORE_SWAP_OUT_THRESHOLD = "telco_score_swap_out_threshold"


PRODUCT_FINANCING_UPLOAD_ACTION_CHOICES = (
    ("Loan Creation", ("Loan Creation")),
    ("Loan Disbursement", ("Loan Disbursement")),
    ("Loan Repayment", ("Loan Repayment")),
    ("Lender Approval", ("Lender Approval")),
)


PRODUCT_FINANCING_LOAN_CREATION_UPLOAD_HEADERS = [
    "Application XID",
    "Name",
    "Product ID",
    "Amount Requested (Rp)",
    "Tenor",
    "Tenor type",
    "Interest Rate",
    "Provision Rate",
    "Loan Start Date",
    "is_pass",
    "notes",
]


PRODUCT_FINANCING_LOAN_DISBURSEMENT_UPLOAD_HEADERS = [
    "loan_xid",
    "disburse_time",
    "is_pass",
    "notes",
]


PRODUCT_FINANCING_LOAN_REPAYMENT_UPLOAD_HEADERS = [
    "NIK",
    "Repayment Date",
    "Total Repayment",
    "is_success",
    "notes",
]


PRODUCT_FINANCING_LENDER_APPROVAL_UPLOAD_HEADERS = [
    "Loan XID",
    "Decision",
    "Notes",
]


class ProductFinancingUploadActionType:
    LOAN_CREATION = PRODUCT_FINANCING_UPLOAD_ACTION_CHOICES[0][0]
    LOAN_DISBURSEMENT = PRODUCT_FINANCING_UPLOAD_ACTION_CHOICES[1][1]
    LOAN_REPAYMENT = PRODUCT_FINANCING_UPLOAD_ACTION_CHOICES[2][1]
    LENDER_APPROVAL = PRODUCT_FINANCING_UPLOAD_ACTION_CHOICES[3][1]


class PartnershipProductCategory:
    MERCHANT_FINANCING = "merchant_financing"
    EMPLOYEE_FINANCING = "employee_financing"
    MF_EFISHERY_NEW = "merchant_financing_new_efishery"


class PartnershipFundingFacilities:
    SUPPLY_CHAIN_FINANCING = "Supply Chain Financing"
    EMPLOYEE_FINANCING = "Employee Financing"
    INVOICE_FINANCING = "Invoice Financing"
    MITRA_BISNIS = "Mitra Bisnis"
    PENERIMA_DANA = "Penerima Dana"


class PartnershipFeatureNameConst(object):
    PARTNERSHIP_MAX_PLATFORM_CHECK_USING_FDC = 'partnership_max_platform_check_using_fdc'
    MERCHANT_FINANCING_LATE_FEE = 'merchant_financing_late_fee'
    PARTNERSHIP_DETOKENIZE = "partnership_detokenize"
    LEADGEN_PARTNER_WEBAPP_OTP_REGISTER = "leadgen_partner_otp_register"
    LIVENESS_ENABLE_IMAGE_ASYNC = 'liveness_enable_image_async'
    PARTNERSHIP_DANA_COLLECTION_BUCKET_CONFIGURATION = (
        "partnership_dana_collection_bucket_configuration"
    )
    LEADGEN_OTP_SETTINGS = 'leadgen_otp_settings'
    # this will cover application with partner referral code or partner onelink
    FORCE_FILLED_PARTNER_CONFIG = 'forced_filled_partner_config'
    LENDER_MATCHMAKING_BY_PARTNER = 'lender_matchmaking_by_partner'
    PARTNERSHIP_DIGISIGN_PRICING = 'partnership_digisign_pricing'
    SEND_SKRTP_OPTION_BY_PARTNER = 'send_skrtp_option_by_partner'
    MERCHANT_FINANCING_LIMIT_REPLENISHMENT = 'merchant_financing_limit_replenishment'
    PARTNERSHIP_DANA_AUTH_CONFIG = 'partnership_dana_auth_config'
    DANA_BLOCK_RECALCULATE_ACCOUNT_LIMIT = 'dana_block_recalculate_account_limit'
    SEND_EMAIL_DISBURSEMENT_NOTIFICATION = 'send_email_disbursement_notification'
    PIN_CONFIG = 'pin_config'
    LEADGEN_LIVENESS_SETTINGS = 'leadgen_liveness_settings'
    LEADGEN_OTP_SETTINGS = 'leadgen_otp_settings'
    LEADGEN_WEB_BASE_URL = "leadgen_web_base_url"
    LEADGEN_RESET_PIN_BASE_URL = "reset_pin_base_url"
    LEADGEN_STANDARD_GOOGLE_OAUTH_REGISTER_PARTNER = (
        "leadgen_standard_google_oauth_register_partner"
    )
    MFSP_PG_SERVICE_ENABLEMENT = 'mfsp_pg_service_enablement'
    DUKCAPIL_FR_THRESHOLD_MFSP = 'dukcapil_fr_threshold_mfsp'
    DUKCAPIL_FR_THRESHOLD_AXIATA = 'dukcapil_fr_threshold_axiata'
    LEADGEN_WEBAPP_CONFIG_RESUME_STUCK_105 = 'leadgen_webapp_config_resume_stuck_105'
    DANA_REPAYMENT_VERSION = 'dana_repayment_version'
    TRIGGER_RESUME_DANA_LOAN_STUCK_211 = 'trigger_resume_dana_loan_stuck_211'


class PartnershipXIDGenerationMethod(Enum):
    UNIX_TIME = 1
    DATETIME = 2
    PRODUCT_LINE = 3


class PartnershipPIIMappingCustomerXid(str):

    TABLE = {
        'auth_user': "object.customer.customer_xid",
        'application': "object.customer.customer_xid",
        'customer': "object.customer_xid",
        'danacustomerdata': "object.customer.customer_xid",
        'partnershipcustomerdata': "object.customer.customer_xid",
        'partnershipapplicationdata': "object.application.customer.customer_xid",
        'axiatacustomerdata': "object.application.customer.customer_xid",
        'merchant': "object.customer.customer_xid",
    }


class PartnershipTelcoScoringStatus(object):
    PASSED_SWAP_IN = "passed_swap_in"
    FAILED_SWAP_IN = "failed_swap_in"
    FEATURE_NOT_ACTIVE = "feature_not_active"
    OPERATOR_NOT_ACTIVE = "operator_not_active"
    OPERATOR_NOT_FOUND = "operator_not_found"
    APPLICATION_NOT_FOUND = "application_not_found"
    FAILED_TELCO_SCORING = "failed_telco_scoring"
    EMPTY_RESULT = "empty_result"

    @classmethod
    def bad_result_list(cls):
        return [
            cls.APPLICATION_NOT_FOUND,
            cls.FAILED_SWAP_IN,
        ]

    @classmethod
    def bypass_result_list(cls):
        return [
            cls.OPERATOR_NOT_ACTIVE,
            cls.FEATURE_NOT_ACTIVE,
        ]

    @classmethod
    def not_found_result_list(cls):
        return [
            cls.OPERATOR_NOT_FOUND,
            cls.EMPTY_RESULT,
        ]


MALICIOUS_PATTERN = {
    "SQL Injection": r"('|--|;|/\*|\*/|\bSELECT\b|\bUPDATE\b|\bDELETE\b|\bINSERT\b|\bTABLE\b|\bDROP"
    r"\b|\bWHERE\b|%20|%27|%22|UNION\s+SELECT|OR\s+1=1|AND\s+1=1|%27\s+AND\s+1=1|-"
    r"-|\bEXEC\b|\bXP\_\b|\bCONVERT\b)",
    "XSS": r"<.*?>|&lt;.*?&gt;|\b(alert|script|on\w*|eval|src|javascript|img|iframe|svg|document\."
    r"location|window\.location|<a\s+href\s*=.*?javascript:)\b",
    "Command Injection": r"(cat\s|system\(|\||\$|\bgrep\b|\bexec\b|nc\s+-e\s+|ping\s+-c\s+|reboot|"
    r"rm\s+|wget\s+|curl\s+|dd\s+|bash\s+-i\s+|id\s+|whoami)",
    "Path Traversal": r"(C:\\|/etc/|/tmp/|\.{2}/|\\\.\.|%2e%2e%2f|%252e%252e%252f|/bin/|/usr/|%c0%"
    r"af%c0%afetc%c0%afpasswd)|(\.\.\/)+|(\.\.%2f)+|(\.\.%252f)+",
    "Template Injection": r"\{\{.*?\}\}|{{\w+}}",
    "Shell Injection": r"(if\s\[|then|echo\s|\$PATH|&&|\|\||\$(\s*|\w+))",
    "Local File Inclusion": r"(?:\.\./|\.\.\\|/etc/passwd|/proc/|/tmp/|/var/|php://|data://|/"
    r"windows/|/winnt/|/system32/|boot\.ini|convert\.base64-encode|"
    r"resource=|input|text/plain;base64)",
    "LDAP Injection": r"(\*\)\(|\)\(|\buid=|\bcn=|\bobjectClass=|\badmin\b|\bpassword=|\b\|\(|\(&)",
}


class PartnershipCLIKScoringStatus(object):
    PASSED_SWAP_IN = "passed_swap_in"
    FAILED_SWAP_IN = "failed_swap_in"
    FEATURE_NOT_ACTIVE = "feature_not_active"
    APPLICATION_NOT_FOUND = "application_not_found"
    PASSED_CLICK_SCORING = "passed_click_scoring"
    FAILED_CLICK_SCORING = "failed_click_scoring"
    EMPTY_RESULT = "empty_result"
    PASSED_CLIK_MODEL = "passed_clik_model"
    FAILED_CLIK_MODEL = "failed_clik_model"

    @classmethod
    def bad_result_list(cls):
        return [
            cls.APPLICATION_NOT_FOUND,
            cls.FAILED_SWAP_IN,
            cls.FAILED_CLIK_MODEL,
        ]

    @classmethod
    def bypass_result_list(cls):
        return [
            cls.FEATURE_NOT_ACTIVE,
        ]


class PartnershipClikModelResultStatus(object):
    IN_PROGRESS = 'in_progress'
    SUCCESS = 'success'
    FAILED = 'failed'


class ErrorType:
    ALERT = 'alert'


class LeadgenRateLimit:
    FORGOT_PIN_MAX_COUNT = 20
    FORGOT_PIN_REDIS_KEY = "api/leadgen/forgot-pin:"
    CHANGE_PIN_VERIFICATION_MAX_COUNT = 7
    CHANGE_PIN_VERIFICATION_REDIS_KEY = 'api/leadgen/pin/verify:'
    CHANGE_PIN_OTP_REQUEST_MAX_COUNT = 7
    CHANGE_PIN_OTP_REQUEST_REDIS_KEY = 'api/leadgen/otp/change-pin/request:'


class DateFormatString:
    DATE_WITH_TIME = "%Y-%m-%dT%H:%M:%S:%f"
    DATE_WITHOUT_TIME = "%Y-%m-%d"
    YEAR_MONTH = "%Y-%m"
