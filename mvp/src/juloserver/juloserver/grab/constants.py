from collections import namedtuple
from django.conf import settings
from juloserver.julo.statuses import LoanStatusCodes

GRAB_API_URL = settings.GRAB_API_URL
GRAB_ACCOUNT_LOOKUP_NAME = "GRAB"

GRAB_PERSONAL_IDENTITY_FIELDS = ('ktp', 'fullname', 'dob', 'gender', 'address_kodepos',
                                 'address_provinsi', 'address_kabupaten', 'address_kecamatan',
                                 'address_kelurahan',
                                 'marital_status', 'dependent', 'mobile_phone_1', 'mobile_phone_2')

GRAB_APPLICATION_FIELDS = GRAB_PERSONAL_IDENTITY_FIELDS + (
'close_kin_name', 'close_kin_mobile_phone',
'kin_relationship', 'kin_name', 'kin_mobile_phone',
'job_type', 'job_industry',
'company_name', 'last_education', 'bank_name',
'name_in_bank', 'bank_account_number', 'loan_purpose',
'loan_purpose_desc')

GRAB_IMAGE_TYPES = ['ktp_self', 'selfie', 'crop_selfie']

GRAB_CUSTOMER_NAME = "GRAB INTEGRATION CUSTOMER"

grab_status_mapping = namedtuple('grab_status_mapping',
                                 ['list_code', 'additional_check', 'mapping_status'],
                                 defaults=(None, None, None))
grab_rejection_mapping = namedtuple(
    'grab_rejection_mapping',
    ['application_loan_status', 'additional_check', 'mapping_status'])


class GrabUserType(object):
    DAX = "DAX"


grab_status_mapping_statuses = (
    grab_status_mapping(
        list_code=0,
        mapping_status="Registered, Application longform"
    ),
    grab_status_mapping(
        list_code=100,
        mapping_status="Registered, Application longform"
    ),
    grab_status_mapping(
        list_code=105,
        mapping_status="Application longform submitted"
    ),
    grab_status_mapping(
        list_code=106,
        mapping_status="Application longform expired"
    ),
    grab_status_mapping(
        list_code=120,
        mapping_status="Application verification"
    ),
    grab_status_mapping(
        list_code=121,
        mapping_status="Application verification"
    ),
    grab_status_mapping(
        list_code=122,
        mapping_status="Application verification"
    ),
    grab_status_mapping(
        list_code=133,
        mapping_status="Application flagged for fraud"
    ),
    grab_status_mapping(
        list_code=131,
        mapping_status="Application re-submission requested"
    ),
    grab_status_mapping(
        list_code=132,
        mapping_status="Application re-submitted"
    ),
    grab_status_mapping(
        list_code=135,
        mapping_status="Application denied"
    ),
    grab_status_mapping(
        list_code=136,
        mapping_status="Resubmission request abandoned"
    ),
    grab_status_mapping(
        list_code=137,
        mapping_status="Application cancelled by customer"
    ),
    grab_status_mapping(
        list_code=175,
        mapping_status="Application bank name validation"
    ),
    grab_status_mapping(
        list_code=190,
        additional_check='Inactive Loan',
        mapping_status="Account activated"
    ),
    grab_status_mapping(
        list_code=190,
        additional_check='No Inactive Loan',
        mapping_status="Loan application completed"
    ),
)

grab_status_description = (
    grab_status_mapping(
        list_code=[LoanStatusCodes.FUND_DISBURSAL_ONGOING,
                   LoanStatusCodes.MANUAL_FUND_DISBURSAL_ONGOING],
        mapping_status="Approved - Pending disbursal"
    ),
    grab_status_mapping(
        list_code=[LoanStatusCodes.LENDER_REJECT],
        mapping_status="Rejected"
    ),
    grab_status_mapping(
        list_code=[LoanStatusCodes.LOAN_1DPD, LoanStatusCodes.LOAN_5DPD,
                   LoanStatusCodes.LOAN_30DPD, LoanStatusCodes.LOAN_60DPD,
                   LoanStatusCodes.LOAN_90DPD, LoanStatusCodes.LOAN_120DPD,
                   LoanStatusCodes.LOAN_150DPD, LoanStatusCodes.LOAN_180DPD],
        mapping_status="Overdue"
    ),
    grab_status_mapping(
        list_code=[LoanStatusCodes.RENEGOTIATED],
        mapping_status="Restructured"
    ),
    grab_status_mapping(
        list_code=[LoanStatusCodes.PAID_OFF],
        mapping_status="Fully Repaid"
    ),
    grab_status_mapping(
        list_code=[241],
        mapping_status="Deductions Paused"
    ),
)

grab_rejection_mapping_statuses = (
    grab_rejection_mapping(
        application_loan_status=135,
        additional_check="application_date_of_birth",
        mapping_status="Age not met"
    ),
    grab_rejection_mapping(
        application_loan_status=135,
        additional_check="fdc_inquiry_check",
        mapping_status="FDC Binary Check"
    ),
    grab_rejection_mapping(
        application_loan_status=135,
        additional_check="blacklist_customer_check",
        mapping_status="DTTOT Blacklist"
    ),
    grab_rejection_mapping(
        application_loan_status=135,
        additional_check="grab_application_check",
        mapping_status="Negative payment history with JULO"
    ),
    grab_rejection_mapping(
        application_loan_status=135,
        additional_check="grab_phone_number_check",
        mapping_status="Registered phone number exists"
    ),
    grab_rejection_mapping(
        application_loan_status=135,
        additional_check="Failed agent check",
        mapping_status="Failed agent check"
    ),
    grab_rejection_mapping(
        application_loan_status=135,
        additional_check="bank account not under own name",
        mapping_status="Bank account not under own name"
    ),
    grab_rejection_mapping(
        application_loan_status=135,
        additional_check="loan_offer_no_longer_active",
        mapping_status="Loan offer no longer active"
    ),
    grab_rejection_mapping(
        application_loan_status=135,
        additional_check="failed dv other",
        mapping_status="failed dv other"
    ),
    grab_rejection_mapping(
        application_loan_status=135,
        additional_check="failed dv expired ktp",
        mapping_status="failed dv expired ktp"
    ),
    grab_rejection_mapping(
        application_loan_status=135,
        additional_check="failed dv identity",
        mapping_status="failed dv identity"
    ),

    grab_rejection_mapping(
        application_loan_status=133,
        additional_check=None,
        mapping_status="Fraud suspicion based on verification"
    ),
    grab_rejection_mapping(
        application_loan_status=131,
        additional_check="KTP blurry",
        mapping_status="Document Resubmission - KTP blurry"
    ),
    grab_rejection_mapping(
        application_loan_status=131,
        additional_check="KTP needed",
        mapping_status="Document Resubmission - KTP needed"
    ),
    grab_rejection_mapping(
        application_loan_status=131,
        additional_check="Selfie needed",
        mapping_status="Document Resubmission - Selfie needed"
    ),
    grab_rejection_mapping(
        application_loan_status=131,
        additional_check="Selfie blurry",
        mapping_status="Document Resubmission - Selfie blurry"
    ),
    grab_rejection_mapping(
        application_loan_status=131,
        additional_check="Other",
        mapping_status="Document Resubmission - Other"
    ),
    grab_rejection_mapping(
        application_loan_status=137,
        additional_check=None,
        mapping_status="Customer requested to cancel"
    ),
    grab_rejection_mapping(
        application_loan_status=106,
        additional_check=None,
        mapping_status="Application Expired"
    ),
    grab_rejection_mapping(
        application_loan_status=136,
        additional_check=None,
        mapping_status="Document Resubmission Expired"
    ),
    grab_rejection_mapping(
        application_loan_status=217,
        additional_check=None,
        mapping_status="Loan Agreement Expired"
    ),
)

OTHER_DOCUMENTS_RESUBMISSION = [
    'SIM needed', 'Informasi Iuran BPJS Ketenagakerjaan needed',
    'Surat Keterangan Kerja needed', 'Mutasi Rekening needed',
    'ID Pegawai needed', 'NPWP needed', 'Salary doc blurry', 'Salary doc needed'
]

GRAB_INTELIX_CALL_DELAY_DAYS = 7

TIME_DELAY_IN_MINUTES_190 = 15

SPLIT_DATA_FOR_KOLEKO_PER = 500


class GrabErrorCodes(object):
    GE_1 = "GE-1"
    GLO_API_ERROR = "GLOx01"

    GAX_ERROR_CODE = "GAX-{}"
    """
        ERROR CODE LIST FOR GRAB BANK ACCOUNT VALIDATION:
        1. Grab Customer Data not found
        2. Bank Name not Found
        3. Application Not found
        4. Predisbursal Check 1 failed
        5. Predisbursal Check 2 failed
        6. Account Number Validation Failed With incorrect data
        7. Account Number Validation Failed With Less than 10 digits
        8. General Error for grab bank details pre-fill
        9 General Error for grab submit bank details
        10. Invalid application status
        11. No data in grab_api_log for last 5 min for pre_disbursal_check
    """

    GAP_ERROR_CODE = "GAP-{}"
    """
        ERROR CODE LIST FOR GRAB PROFILE PAGE:
        1. Grab Customer Data not found
        2. Application Not found
    """


class GrabErrorMessage(object):
    CHANGE_PHONE_REQUEST = "Untuk mendapatkan penawaran pinjaman, pastikan nomor " \
                           "handphone yang terdaftar pada Grab Modal sama dengan " \
                           "nomor handphone yang ada di aplikasi Grab"
    API_TIMEOUT_ERROR_OFFER = "Maaf ya, ada sedikit masalah. Silakan klik \"Coba Lagi\" " \
                              "untuk tampilkan halaman ini, ya!"
    AUTH_ERROR_MESSAGE_4001 = "User not eligible for program"
    AUTH_ERROR_MESSAGE_4002 = "User profile not found"
    AUTH_ERROR_MESSAGE_4006 = "Whitelist country not equal to payments country"
    AUTH_ERROR_MESSAGE_4008 = "User not whitelisted"
    AUTH_ERROR_MESSAGE_4011 = "Error Application Type Invalid"
    AUTH_ERROR_MESSAGE_4014 = "Insufficient Limit"
    AUTH_ERROR_MESSAGE_4015 = "Error Application Type Invalid"
    AUTH_ERROR_MESSAGE_4025 = "Insufficient Limit"
    AUTH_ERROR_MESSAGE_5001 = "Max retry reached"
    AUTH_ERROR_MESSAGE_5002 = "Max retry reached"
    AUTH_ERROR_MESSAGE_8002 = "Max retry reached"
    AUTH_ERROR_MESSAGE_API_ERROR = "Grab API Error"

    BANK_VALIDATION_GENERAL_ERROR_MESSAGE = "Mohon maaf, ada kesalahan pada sistem kami mohon " \
                                            "hubungi cs@julo.co.id dengan melampirkan info " \
                                            "permasalahan ini"

    BANK_VALIDATION_PRE_DISBURSAL_CHECK_ERROR_MESSAGE = "Pastikan nomor rekening sama dengan nomor " \
                                                        "rekening yang terdaftar di Grab"

    BANK_VALIDATION_INCORRECT_ACCOUNT_NUMBER = "Nomor rekening bank tidak valid, " \
                                               "mohon isi dengan angka dan tanpa spasi"

    BANK_VALIDATION_MINIMUM_DIGIT_IN_ACCOUNT_NUMBER = "Minimal masukkan lebih dari 10 karakter"

    PROFILE_PAGE_GENERAL_ERROR_MESSAGE = "Mohon maaf, ada kesalahan pada sistem kami mohon " \
                                         "hubungi cs@julo.co.id dengan melampirkan info " \
                                         "permasalahan ini"
    GRAB_API_LOG_EXPIRED_FOR_PRE_DISBURSAL_CHECK = "Mohon verifikasi nomor rekening anda"

    BANK_VALIDATION_HAS_LOANS_ACTIVE = "Pastikan anda tidak memiliki pinjaman aktif"

    NIK_EMAIL_INVALID = "NIK / Email Tidak Valid atau Sudah Terdaftar"
    USE_VALID_NIK = (
        "Silahkan masuk atau gunakan NIK / Email yang valid dan "
        "belum didaftarkan di produk JULO yang lain, ya."
    )
    OTP_LIMIT_REACHED = (
        "Kamu sudah kirim ulang kode OTP sebanyak {max_otp_request} kali. "
        "Harap tunggu {wait_time_minutes} menit untuk mencoba lagi, ya!"
    )
    OTP_INACTIVE = "Kesempatan kamu telah habis, silakan coba lagi"
    OTP_RESEND_TIME_INEFFICIENT = (
        'Masukkan kode OTP yang sudah kamu terima atau '
        'tunggu beberapa saat untuk kirim ulang OTP'
    )
    OTP_CODE_INVALID = 'Kode yang kamu masukkan salah'
    LINK_CUSTOMER_EXISTS_MESSAGE = "Grab customer Data exist. Please Login."
    PROMO_CODE_ALPHA_NUMERIC = 'Promo code should be alpha numeric'
    PROMO_CODE_MIN_CHARACTER = 'Promo code should contain more than 2 character'
    PROMO_CODE_VERIFIED_SUCCESS = 'Kode Promo berhasil diverifikasi'
    PROMO_CODE_INVALID = 'Kode Promo tidak valid'
    NO_REKENING_NOT_CONFIRMED = 'Nomor rekening gagal terkonfirmasi'


SLACK_CAPTURE_FAILED_CHANNEL = "grab_capture_failed"
GRAB_FAILED_3MAX_CREDITORS_CHECK = 'Failed 3 max creditors check'


class GrabWriteOffStatus(object):
    MANUAL_WRITE_OFF = "Manual Write off"
    EARLY_WRITE_OFF = "Early Write off"
    WRITE_OFF_180_DPD = "180 DPD Write off"
    LEGACY_WRITE_OFF = "Write off"

    GRAB_180_DPD_CUT_OFF = 181


GRAB_BULK_UPDATE_SIZE = 200

# Referral
GRAB_REFERRAL_CASHBACK = 60000
GRAB_CUSTOMER_BASE_ID = 1000000000
GRAB_ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
GRAB_NUMBER = "123456789"

GRAB_C_SCORE_FILE_PATH = r'/media/intelix_grab_c_score/c_score_file.csv'

# File Transfer
GRAB_FILE_TRANSFER_LOAN_LIMIT = 1000
GRAB_FILE_TRANSFER_DAILY_TRANSACTION_LIMIT = 25000


class AccountHaltStatus(object):
    HALTED = 'halted'
    HALTED_UPDATED_RESUME_LOGIC = 'halted_updated_logic'
    RESUMED = 'resumed'
    CHOICES = (
        (HALTED, HALTED),
        (HALTED_UPDATED_RESUME_LOGIC, HALTED_UPDATED_RESUME_LOGIC),
        (RESUMED, RESUMED),
    )


class FeatureSettingParameters(object):
    POPULATE_DAILY_TXN_SCHEDULE = 'populate_daily_txn_schedule'
    POPULATE_LOAN_SCHEDULE = 'populate_loan_schedule'
    LOAN_PER_FILE = 'loan_per_file'
    TRANSACTION_PER_FILE = 'transaction_per_file'

    GRAB_FILE_TRANSFER_PARAMETERS = {POPULATE_DAILY_TXN_SCHEDULE, POPULATE_LOAN_SCHEDULE,
                                     LOAN_PER_FILE, TRANSACTION_PER_FILE}


class GrabApplicationConstants(object):
    JOB_INDUSTRY_DEFAULT = 'Transportasi'
    JOB_TYPE_DEFAULT = 'Pengusaha'
    COMPANY_NAME_DEFAULT = 'Grab Indonesia'


class GrabApplicationPageNumberMapping(object):
    KTP_IMAGE = 'ktp'
    SELFIE_IMAGE = 'selfie_ktp'
    NIK = 'nik'
    EMAIL = 'email'
    FULLNAME = 'fullname'
    DOB = 'dob'
    GENDER = 'gender'
    LAST_EDUCATION = 'last_education'
    ADDRESS_PROVINSI = 'address_province'
    ADDRESS_KABUPATEN = 'address_regency'
    ADDRESS_KECAMATAN = 'address_district'
    ADDRESS_KELURAHAN = 'address_subdistrict'
    ADDRESS_KODEPOS = 'address_zipcode'
    ADDRESS_STREET_NUMBER = 'address'
    MARITAL_STATUS = 'marital_status'
    DEPEND = 'total_dependent'
    MOBILE_PHONE1 = 'primary_phone_number'
    MOBILE_PHONE2 = 'secondary_phone_number'

    CLOSE_KIN_NAME = 'close_kin_name'
    CLOSE_KIN_MOBILE_PHONE = 'close_kin_mobile_phone'
    KIN_RELATIONSHIP = 'kin_relationship'
    KIN_NAME = 'kin_name'
    KIN_MOBILE_PHONE = 'kin_mobile_phone'

    MONTHLY_INCOME = 'monthly_income'
    BANK_NAME = 'bank_name'
    BANK_ACCOUNT_NUMBER = 'bank_account_number'
    LOAN_PURPOSE = 'loan_purpose'
    REFERRAL_CODE = 'referral_code'

    PAGE_1 = {
        KTP_IMAGE, SELFIE_IMAGE, NIK, EMAIL, FULLNAME, DOB, GENDER, LAST_EDUCATION,
        ADDRESS_PROVINSI, ADDRESS_KABUPATEN, ADDRESS_KECAMATAN,
        ADDRESS_KELURAHAN, ADDRESS_KODEPOS, MARITAL_STATUS, DEPEND, MOBILE_PHONE1,
        MOBILE_PHONE2, ADDRESS_STREET_NUMBER
    }

    PAGE_2 = {
        CLOSE_KIN_NAME, CLOSE_KIN_MOBILE_PHONE, KIN_RELATIONSHIP, KIN_NAME, KIN_MOBILE_PHONE
    }

    PAGE_3 = {
        MONTHLY_INCOME, BANK_NAME, BANK_ACCOUNT_NUMBER, LOAN_PURPOSE, REFERRAL_CODE, FULLNAME
    }

    @staticmethod
    def mapping_application_to_fe_variable_name(variable: str):
        if variable == 'ktp':
            updated_variable = GrabApplicationPageNumberMapping.NIK
        elif variable == 'dependent':
            updated_variable = GrabApplicationPageNumberMapping.DEPEND
        elif variable == 'selfie_image_url':
            updated_variable = GrabApplicationPageNumberMapping.SELFIE_IMAGE
        elif variable == 'ktp_image_url':
            updated_variable = GrabApplicationPageNumberMapping.KTP_IMAGE
        elif variable == 'mobile_phone_1':
            updated_variable = GrabApplicationPageNumberMapping.MOBILE_PHONE1
        elif variable == 'mobile_phone_2':
            updated_variable = GrabApplicationPageNumberMapping.MOBILE_PHONE2
        elif variable == 'address_street_num':
            updated_variable = GrabApplicationPageNumberMapping.ADDRESS_STREET_NUMBER
        elif variable == 'address_provinsi':
            updated_variable = GrabApplicationPageNumberMapping.ADDRESS_PROVINSI
        elif variable == 'address_kabupaten':
            updated_variable = GrabApplicationPageNumberMapping.ADDRESS_KABUPATEN
        elif variable == 'address_kecamatan':
            updated_variable = GrabApplicationPageNumberMapping.ADDRESS_KECAMATAN
        elif variable == 'address_kelurahan':
            updated_variable = GrabApplicationPageNumberMapping.ADDRESS_KELURAHAN
        elif variable == 'address_kodepos':
            updated_variable = GrabApplicationPageNumberMapping.ADDRESS_KODEPOS
        else:
            updated_variable = variable
        return updated_variable

    @staticmethod
    def mapping_fe_variable_name_to_application(variable: str):
        if variable == GrabApplicationPageNumberMapping.NIK:
            updated_variable = 'ktp'
        elif variable == GrabApplicationPageNumberMapping.DEPEND:
            updated_variable = 'dependent'
        elif variable == GrabApplicationPageNumberMapping.MOBILE_PHONE1:
            updated_variable = 'mobile_phone_1'
        elif variable == GrabApplicationPageNumberMapping.MOBILE_PHONE2:
            updated_variable = 'mobile_phone_2'
        elif variable == GrabApplicationPageNumberMapping.ADDRESS_STREET_NUMBER:
            updated_variable = 'address_street_num'
        elif variable == GrabApplicationPageNumberMapping.ADDRESS_PROVINSI:
            updated_variable = 'address_provinsi'
        elif variable == GrabApplicationPageNumberMapping.ADDRESS_KABUPATEN:
            updated_variable = 'address_kabupaten'
        elif variable == GrabApplicationPageNumberMapping.ADDRESS_KECAMATAN:
            updated_variable = 'address_kecamatan'
        elif variable == GrabApplicationPageNumberMapping.ADDRESS_KELURAHAN:
            updated_variable = 'address_kelurahan'
        elif variable == GrabApplicationPageNumberMapping.ADDRESS_KODEPOS:
            updated_variable = 'address_kodepos'
        elif variable == GrabApplicationPageNumberMapping.SELFIE_IMAGE:
            updated_variable = 'selfie_image_url'
        elif variable == GrabApplicationPageNumberMapping.KTP_IMAGE:
            updated_variable = 'ktp_image_url'
        else:
            updated_variable = variable
        return updated_variable

    @staticmethod
    def get_fields_based_on_page_number(page: int):
        if page == 1:
            return GrabApplicationPageNumberMapping.PAGE_1
        elif page == 2:
            return GrabApplicationPageNumberMapping.PAGE_2
        elif page == 3:
            return GrabApplicationPageNumberMapping.PAGE_3
        elif page == 4:
            return (
                        GrabApplicationPageNumberMapping.PAGE_1 | GrabApplicationPageNumberMapping.PAGE_2
                        | GrabApplicationPageNumberMapping.PAGE_3)
        else:
            return {}


class GrabRobocallConstant(object):
    """
        THE Grab Robocall Ranges based on C score
        The ranges are:
            high_c_score = 200 - 449
            medium_c_score = 450 - 599
            low_c_score = 600 - 800
        the constants are in the format (low score, high score)
    """
    HIGH_C_SCORE_RANGE = (200, 449)
    MEDIUM_C_SCORE_RANGE = (450, 599)
    LOW_C_SCORE_RANGE = (600, 800)

    REDIS_KEY_FOR_ROBOCALL = 'payment_set_for_grab_robocall'
    ROBOCALL_BATCH_SIZE = 1000


class GrabAuthStatus(object):
    PENDING = 'PENDING'
    SUCCESS = 'SUCCESS'
    FAILED = 'FAILED'
    FAILED_4002 = 'FAILED_4002'


class GrabAuthAPIErrorCodes(object):
    ERROR_CODE_4001 = 4001
    ERROR_CODE_4002 = 4002
    ERROR_CODE_4006 = 4006
    ERROR_CODE_4008 = 4008
    ERROR_CODE_4011 = 4011
    ERROR_CODE_4014 = 4014
    ERROR_CODE_4015 = 4015
    ERROR_CODE_4025 = 4025
    ERROR_CODE_5001 = 5001
    ERROR_CODE_5002 = 5002
    ERROR_CODE_8002 = 8002


GRAB_AUTH_API_MAPPING = {
    GrabAuthAPIErrorCodes.ERROR_CODE_4001: (
        LoanStatusCodes.LENDER_REJECT, GrabErrorMessage.AUTH_ERROR_MESSAGE_4001),
    GrabAuthAPIErrorCodes.ERROR_CODE_4002: (
        LoanStatusCodes.LENDER_REJECT, GrabErrorMessage.AUTH_ERROR_MESSAGE_4002),
    GrabAuthAPIErrorCodes.ERROR_CODE_4006: (
        LoanStatusCodes.LENDER_REJECT, GrabErrorMessage.AUTH_ERROR_MESSAGE_4006),
    GrabAuthAPIErrorCodes.ERROR_CODE_4008: (
        LoanStatusCodes.LENDER_REJECT, GrabErrorMessage.AUTH_ERROR_MESSAGE_4008),
    GrabAuthAPIErrorCodes.ERROR_CODE_4011: (
        LoanStatusCodes.LENDER_REJECT, GrabErrorMessage.AUTH_ERROR_MESSAGE_4011),
    GrabAuthAPIErrorCodes.ERROR_CODE_4014: (
        LoanStatusCodes.LENDER_REJECT, GrabErrorMessage.AUTH_ERROR_MESSAGE_4014),
    GrabAuthAPIErrorCodes.ERROR_CODE_4015: (
        LoanStatusCodes.LENDER_REJECT, GrabErrorMessage.AUTH_ERROR_MESSAGE_4015),
    GrabAuthAPIErrorCodes.ERROR_CODE_4025: (
        LoanStatusCodes.LENDER_REJECT, GrabErrorMessage.AUTH_ERROR_MESSAGE_4025),
    GrabAuthAPIErrorCodes.ERROR_CODE_5001: (
        LoanStatusCodes.LENDER_REJECT, GrabErrorMessage.AUTH_ERROR_MESSAGE_5001),
    GrabAuthAPIErrorCodes.ERROR_CODE_5002: (
        LoanStatusCodes.LENDER_REJECT, GrabErrorMessage.AUTH_ERROR_MESSAGE_5002),
    GrabAuthAPIErrorCodes.ERROR_CODE_8002: (
        LoanStatusCodes.LENDER_REJECT, GrabErrorMessage.AUTH_ERROR_MESSAGE_8002),
    'default': (
        LoanStatusCodes.LENDER_REJECT, GrabErrorMessage.AUTH_ERROR_MESSAGE_API_ERROR),
}


class GrabBankValidationStatus(object):
    INITIATED = 'INITIATED'
    FAILED = 'FAILED'
    IN_PROGRESS = 'IN_PROGRESS'
    SUCCESS = 'SUCCESS'


class GrabSMSTemplateCodes(object):
    GRAB_SMS_APP_100_EXPIRE_IN_ONE_DAY = 'grab_sms_app_100_expire_in_1_day'
    GRAB_SMS_FOR_PROVIDE_DEGISIGN = 'grab_sms_for_provide_degisign'
    GRAB_SMS_APP_AT_131 = 'grab_sms_app_at_131'
    GRAB_SMS_APP_AT_131_FOR_24_HOUR = 'grab_sms_app_at_131_for_24_hour'


class GrabEmailTemplateCodes(object):
    GRAB_EMAIL_APP_AT_131 = 'grab_email_app_at_131'

GRAB_MAX_CREDITORS_REACHED_ERROR_MESSAGE = "Failed {} max creditors check"

GRAB_AUTH_FAILED_3_MAX_CREDS_ERROR_MESSAGE = "3 max creditors, auth failed"

GRAB_BLACKLIST_CUSTOMER = "blacklist_customer_check"


class PromoCodeStatus(object):
    INITIATED = "initiated"
    APPLIED = "applied"

    CHOICES = (
        (INITIATED, INITIATED),
        (APPLIED, APPLIED)
    )


class GrabExperimentConst(object):
    NEW_LOAN_OFFER_PAGE_FEATURE = 'loan_offer_page_new_design'
    CONTROL_TYPE = 'control'
    VARIATION_TYPE = 'variation'
    DAYS_OF_MONTH = 30


class GrabExperimentGroupSource(object):
    GROWTHBOOK = 'Growthbook'


class GrabFeatureNameConst(object):
    GRAB_POPULATING_CONFIG = 'grab_populating_config'
    GRAB_CRS_FLOW_BLOCKER = 'grab_flow_blocker'
    GRAB_FDC_AUTO_APPROVAL = 'grab_fdc_auto_approval'
    GRAB_HALT_RESUME_DISBURSAL_PERIOD = 'grab_halt_resume_disbursal_period'


GRAB_DOMAIN_NAME= {
    'staging': 'grab-staging.julo.co.id',
    'dev': 'grab-staging.julo.co.id',
    'uat': 'grab-uat.julo.co.id',
    'prod': 'grab.julo.co.id',
}


class EmergencyContactErrorConstants(object):
    EXPIRED_LINK = 'Link already expired'
    INVALID_LINK = 'Invalid link'
    USED_LINK = 'Link already used'
    EXPIRED_OR_USED_LINK = 'Link already expired or already used'
    WRONG_FORMAT_CONSENT = 'Wrong format of consent'
    IS_NOT_REJECTED = 'Emergency contact is not rejected'
    SAME_WITH_PREVIOUS_CONTACT = 'Emergency contact data cannot be same as previous contact'


class EmergencyContactConstants(object):
    KIN_APPROVED = 1
    KIN_REJECTED = 2


INFO_CARD_AJUKAN_PINJAMAN_LAGI_DESC = 'retroload home ajukan pinjaman'


class GrabLoanStatus(object):
    ACTIVE_LOAN_STATUS = [
        LoanStatusCodes.CURRENT,
        LoanStatusCodes.LENDER_APPROVAL,
        LoanStatusCodes.FUND_DISBURSAL_ONGOING,
        LoanStatusCodes.MANUAL_FUND_DISBURSAL_ONGOING,
        LoanStatusCodes.LOAN_1DPD,
        LoanStatusCodes.LOAN_5DPD,
        LoanStatusCodes.LOAN_30DPD,
        LoanStatusCodes.LOAN_60DPD,
        LoanStatusCodes.LOAN_90DPD,
        LoanStatusCodes.LOAN_120DPD,
        LoanStatusCodes.LOAN_150DPD,
        LoanStatusCodes.LOAN_180DPD,
        LoanStatusCodes.RENEGOTIATED,
        LoanStatusCodes.FUND_DISBURSAL_FAILED,
    ]


class GrabApiLogConstants(object):
    FAILED_CRS_VALIDATION_ERROR_RESPONSE = 'ErrorCrsFailedValidation'
    ERROR_APPLICATION_ALREADY_EXISTS_RESPONSE = 'ErrorApplicationAlreadyExists'


class GrabMasterLockReasons(object):
    FAILED_CRS_VALIDATION = 'failed_crs_validation'


class GrabMasterLockConstants(object):
    DEFAULT_EXPIRY_HOURS = 24


class ApplicationStatus(object):
    APPROVE = "approve"
    REJECT = "reject"

    CHOICES = (
        (APPROVE, APPROVE),
        (REJECT, REJECT)
    )
