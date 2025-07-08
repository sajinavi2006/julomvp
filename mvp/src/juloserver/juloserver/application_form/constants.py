from juloserver.apiv2.constants import ErrorMessage
from juloserver.julo.constants import OnboardingIdConst, ApplicationStatusCodes


class JuloStarterFormResponseCode:
    CUSTOMER_NOT_FOUND = 'customer_not_found'
    APPLICATION_NOT_FOUND = 'application_not_found'
    APPLICATION_NOT_ALLOW = 'application_not_allow'
    EMAIL_ALREADY_EXIST = 'email_already_exist'
    INVALID_PHONE_NUMBER = 'invalid_phone_number'
    NOT_FINISH_LIVENESS_DETECTION = 'not_finish_liveness_detection'
    USER_NOT_ALLOW = 'user_not_allow'
    SUCCESS = 'success'
    INVALID_NIK = 'invalid_nik'
    INVALID_EMAIL = 'invalid_email'
    BPJS_FEATURE_INACTIVE = 'bpjs_feature_not_active'
    BPJS_SYSTEM_ERROR = 'bpjs_system_error'


class JuloStarterFormResponseMessage:
    CUSTOMER_NOT_FOUND = 'Customer not found'
    APPLICATION_NOT_FOUND = 'Application not found'
    APPLICATION_NOT_ALLOW = 'Application is not allowed'
    EMAIL_ALREADY_EXIST = 'Email sudah ada'
    INVALID_PHONE_NUMBER = 'Nomor HP tidak valid'
    USER_NOT_ALLOW = 'User is not allowed'
    NOT_FINISH_LIVENESS_DETECTION = 'Cek kembali halaman selfie dan ambil ulang foto kamu'
    INVALID_NIK = 'Nomor KTP tidak valid'
    INVALID_EMAIL = 'Email tidak valid'
    BPJS_FEATURE_INACTIVE = 'BPJS not Active'
    BPJS_SYSTEM_ERROR = 'BPJS System Error'


class JuloStarterChangeReason:
    APPLICATION_CANCEL = 'Customer requested to cancel'


class JuloStarterAppCancelResponseCode:
    SUCCESS = 'Success'
    APPLICATION_NOT_FOUND = 'application_not_found'


class JuloStarterAppCancelResponseMessage:
    SUCCESS = 'Application was cancelled'
    APPLICATION_NOT_FOUND = 'Application not found'


class JuloStarterReapplyResponseCode:
    APPLICATION_NOT_FOUND = 'application_not_found'
    CUSTOMER_CAN_NOT_REAPPLY = 'customer_can_not_reapply'
    DEVICE_NOT_FOUND = 'device_not_found'
    SUCCESS = 'success'
    SERVER_ERROR = 'server_error'
    USER_HAS_NO_PIN = 'user_has_no_pin'


class JuloStarterReapplyResponseMessage:
    APPLICATION_NOT_FOUND = 'Application not found'
    CUSTOMER_CAN_NOT_REAPPLY = ErrorMessage.CUSTOMER_REAPPLY
    DEVICE_NOT_FOUND = 'Device not found'
    SUCCESS = 'Application was cancelled'
    SERVER_ERROR = ErrorMessage.GENERAL
    USER_HAS_NO_PIN = 'This customer is not available'


class ApplicationReapplyFields:
    JULO_ONE = (
        'mobile_phone_1',
        'fullname',
        'dob',
        'gender',
        'ktp',
        'email',
        'id',
        'marital_status',
        'spouse_name',
        'spouse_mobile_phone',
        'close_kin_name',
        'close_kin_mobile_phone',
        'bank_name',
        'bank_account_number',
        'address_kabupaten',
        'address_kecamatan',
        'address_kelurahan',
        'address_kodepos',
        'address_provinsi',
        'address_street_num',
        'job_description',
        'job_industry',
        'job_start',
        'job_type',
        'payday',
        'company_name',
        'company_phone_number',
        'monthly_expenses',
        'monthly_income',
        'total_current_debt',
        'birth_place',
        'last_education',
        'home_status',
        'occupied_since',
        'dependent',
        'monthly_housing_cost',
    )

    JULO_STARTER = (
        'ktp',
        'email',
        'fullname',
        'dob',
        'gender',
        'marital_status',
        'mobile_phone_1',
        'mobile_phone_2',
        'address_street_num',
        'address_provinsi',
        'address_kabupaten',
        'address_kecamatan',
        'address_kelurahan',
        'address_kodepos',
        'address_detail',
        'job_type',
        'job_industry',
        'job_description',
        'company_name',
        'payday',
        'last_education',
        'monthly_income',
        'monthly_expenses',
        'total_current_debt',
        'referral_code',
        'onboarding_id',
        'bank_name',
        'bank_account_number',
        'workflow',
        'product_line',
    )


class AllowedOnboarding:
    JULO_PRODUCT_PICKER = {
        OnboardingIdConst.LONGFORM_ID,
        OnboardingIdConst.LONGFORM_SHORTENED_ID,
        OnboardingIdConst.LF_REG_PHONE_ID,
        OnboardingIdConst.LFS_REG_PHONE_ID,
        OnboardingIdConst.JULO_STARTER_ID,
        OnboardingIdConst.LFS_SPLIT_EMERGENCY_CONTACT,
        OnboardingIdConst.SHORTFORM_ID,
        OnboardingIdConst.JULO_360_J1_ID,
        OnboardingIdConst.JULO_360_TURBO_ID,
    }


class JStarterOnboarding:
    """
    List non-J1 by onboarding
    """

    JSTARTER_ONBOARDING = {
        OnboardingIdConst.JULO_STARTER_ID,
        OnboardingIdConst.JULO_360_TURBO_ID,
    }


class ApplicationUpgradeConst:
    """
    Refer to table ops.application_extension
    :0 is not upgraded
    :1 is upgraded to J1 from JTurbo
    """

    MARK_UPGRADED = 1
    NOT_YET_UPGRADED = 0

    OPTIONAL_FIELDS_UPGRADE_FORM = ['mobile_phone_2']
    MANDATORY_UPGRADE_FORM = [
        'birth_place',
        'mother_maiden_name',
        'company_phone_number',
        'monthly_expenses',
        'loan_purpose',
        'total_current_debt',
    ]
    FIELDS_UPGRADE_FORM = MANDATORY_UPGRADE_FORM + OPTIONAL_FIELDS_UPGRADE_FORM


class InfoCardMessageReapply:
    TWO_WEEKS = '2 Minggu.'
    ONE_MONTH = '1 Bulan.'
    TWO_MONTHS = '2 Bulan.'
    THREE_MONTHS = '3 Bulan.'
    HALF_A_YEAR = '6 Bulan'
    ONE_YEAR = '1 Tahun.'

    MESSAGE_FOR_REAPPLY = ' Kamu bisa ajukan upgrade lagi dalam'


class ApplicationFieldsLabels:
    FIELDS = {
        'address_detail': 'Alamat lengkap',
        'dob': 'Tempat tanggal lahir',
        'gender': 'Jenis kelamin',
        'marital_status': 'Status sipil',
        'mobile_phone_1': 'Nomor HP Utama',
        'mother_maiden_name': 'Nama ibu kandung',
        'email': 'Email',
        'company_name': 'Nama Perusahaan',
        'last_education': 'Pendidikan Terakhir',
        'address_street_num': 'Alamat lengkap',
        'ktp': 'Nomor KTP',
        'name_in_bank': 'Nama di dalam Bank',
        'referral_code': 'Kode Referral',
        'payday': 'Tanggal gajian',
        'monthly_income': 'Penghasilan bulanan',
        'monthly_expenses': 'Pengeluaran bulanan',
        'total_current_debt': 'Total cicilan bulanan',
        'mobile_phone_2': 'Nomor HP lainnya',
        'address_provinsi': 'Provinsi',
        'address_kabupaten': 'Kabupaten',
        'address_kecamatan': 'Kecamatan',
        'address_kelurahan': 'Kelurahan',
        'address_kodepos': 'Kode Pos',
        'job_type': 'Tipe pekerjaan',
        'job_industry': 'Bidang pekerjaan',
        'job_description': 'Pekerjaan',
    }


class LabelProductPickerProducts:
    J1 = 'Julo Kredit Digital'
    JSTARTER = 'Julo Turbo'


class LabelFieldsIDFyConst:
    """
    Format {fields_on_idfy / fields_on_db}
    """

    KEY_IN_PROGRESS = 'in_progress'
    KEY_COMPLETED = 'completed'
    KEY_REJECTED = 'rejected'
    KEY_CANCELED = 'canceled'

    KEY_RESOURCE_KTP = 'ktp_1'
    KEY_RESOURCE_SELFIE = 'selfie'
    KEY_RESOURCE_ADDITIONAL_DOCS = 'business_document'

    TRANSFORM_FIELDS = {
        'total_current_debt': 'total_debt',
        'bank_account_number': 'acc_number',
        'monthly_income': 'inc_month',
        'monthly_expenses': 'total_month',
        'payday': 'pay_date',
        'job_start': 'start_job',
        'company_name': 'comp_name',
        'spouse_mobile_phone': 'spouse_no',
        'spouse_name': 'spouse_name',
        'mobile_phone_1': 'mobile_number',
        'kin_mobile_phone': 'family_no',
        'fullname': 'ktp_name',
        'kin_name': 'family_name',
        'spouse_mobile_phone': 'spouse_no',
        'close_kin_name': 'parent_name',
        'address_detail': 'ktp_address',
        'spouse_mobile_phone': 'spouse_no',
        'company_phone_number': 'comp_tele',
        'name_in_bank': 'ktp_name',
    }

    REASON_TO_CONTINUE_FORM = 'Pelanggan telah terputus dari panggilan'

    GENDER_MAPPING = {
        'LAKI-LAKI': 'Pria',
        'LAKI LAKI': 'Pria',
        'PRIA': 'Pria',
        'PEREMPUAN': 'Wanita',
        "WANITA": 'Wanita',
    }

    MARITAL_STATUS_MAPPING = {
        "BELUM KAWIN": "Lajang",
        "LAJANG": "Lajang",
        "KAWIN": "Menikah",
        "MENIKAH": "Menikah",
        "CERAI HIDUP": "Cerai",
        "CERAI": "Cerai",
    }


class IDFyApplicationTagConst:
    SUCCESS_VALUE = 1
    IN_PROGRESS_VALUE = 0

    TAG_NAME = 'is_vcdv'


class ApplicationDirectionConst:
    HOME_SCREEN = 'homescreen'
    PRODUCT_PICKER = 'product_picker'
    FORM_SCREEN = 'form_screen'
    VIDEO_CALL_SCREEN = 'video_webview'


class ApplicationJobSelectionOrder:
    FIRST = "1_job_selected"
    SECOND = "2_job_selected"
    THIRD = "3_job_selected"
    FOURTH = "4_job_selected"
    FIFTH = "5_job_selected"
    SIXTH = "6_job_selected"
    SEVENTH = "7_job_selected"
    EIGHTH = "8_job_selected"


class SwitchProductWorkflowConst:
    CHANGE_REASON = 'switch_product'


class ApplicationEditedConst:
    FIELDS = [
        'ktp_self',
        'selfie',
        'nama',
        'nik',
        'tgl_lahir',
        'tempat',
        'status_perkawinan',
        'jenis_kelamin',
        'alamat',
        'provinci',
        'kota_or_kabupaten',
        'jenis_kelamin',
        'alamat',
        'provinci',
        'kota_or_kabupaten',
        'kecamatan',
        'kel_desa',
        'pekerjaan',
    ]

    APPLICATION_FIELDS_MAPPING = {
        'nik': 'ktp',
        'nama': 'fullname',
        'tempat': 'birth_place',
        'pekerjaan': 'job_type',
        'kel_desa': 'address_kelurahan',
        'provinci': 'address_provinsi',
        'kecamatan': 'address_kecamatan',
        'tgl_lahir': 'dob',
        'jenis_kelamin': 'gender',
        'kota_or_kabupaten': 'address_kabupaten',
        'status_perkawinan': 'marital_status',
        'alamat': 'address_street_num',
    }


class IDFyAgentOfficeHoursConst:
    OPEN_GATE = {
        'hour': 8,
        'minute': 0,
    }

    CLOSED_GATE = {
        'hour': 20,
        'minute': 0,
    }

    MESSAGE_INFO = 'Video call hanya bisa dilakukan pada jam {0}.00 - {1}.00 WIB'.format(
        OPEN_GATE['hour'], CLOSED_GATE['hour']
    )

    FORMAT_WIB_DEFAULT = '{0:02d}.{1:02d}-{2:02d}.{3:02d} WIB'

    TITLE_DEFAULT = 'Jam Operasional (Waktu Indonesia Barat)'
    MESSAGE_DEFAULT = 'Senin-Minggu: ' + FORMAT_WIB_DEFAULT
    MESSAGE_WEEKDAYS = 'Senin-Jumat: ' + FORMAT_WIB_DEFAULT
    MESSAGE_HOLIDAYS = 'Sabtu-Minggu: ' + FORMAT_WIB_DEFAULT
    BTN_MSG_IN = 'Jam operasional ' + FORMAT_WIB_DEFAULT
    BTN_MSG_OUTSIDE = 'Tersedia besok di jam ' + FORMAT_WIB_DEFAULT
    MESSAGE_DAY_OFF_OPERATIONAL = 'Tidak beroperasi'


class EmergencyContactConst:
    SMS_SENT = 0
    CONSENT_ACCEPTED = 1
    CONSENT_REJECTED = 2
    CONSENT_IGNORED = 3

    SMS_TEMPLATE_NAME = 'consent_code_request'
    MESSAGE_APPLICATION_NOT_FOUND = "Aplikasi tidak ditemukan"
    MESSAGE_KIN_MOBILE_PHONE_USED = (
        "Nomor kontak darurat sudah pernah digunakan, harap gunakan nomor lain"
    )
    MESSAGE_KIN_CONSENT_CODE_EXPIRED = 'Kode yang anda masukkan sudah tidak berlaku'
    MESSAGE_KIN_CONSENT_CODE_NOT_FOUND = 'Kode tidak ditemukan'
    MESSAGE_KIN_ALREADY_APPROVED = 'Permintaan kontak darurat anda sudah disetujui'
    MESSAGE_GRACE_PERIOD_PASSED = 'Masa tenggang kontak darurat sudah lewat'

    CONSENT_RESPONDED_VALUE = [CONSENT_ACCEPTED, CONSENT_REJECTED, CONSENT_IGNORED]
    CAPPED_LIMIT_VALUES = [SMS_SENT, CONSENT_REJECTED, None]

    WEBFORM_URL_PROD = 'http://form.julo.co.id'
    WEBFORM_URL_UAT = (
        'https://mtl-webform-uat-git-argatahta-fa473e-julo-frontend-engineering.vercel.app'
    )
    WEBFORM_URL_STAGING = (
        'https://mtl-webform-git-argatahta-rus1-e06900-julo-frontend-engineering.vercel.app'
    )


EMERGENCY_CONTACT_APPLICATION_STATUSES = [
    ApplicationStatusCodes.ACTIVATION_CALL_SUCCESS_AND_BANK_VALIDATE_ONGOING,
    ApplicationStatusCodes.ACTIVATION_AUTODEBET,
]


class IDFyCallbackConst:

    # 4 minutes
    MAX_TIME_OF_DELAY_IDFY_CALLBACK = 4


class GoodFDCX100Const:

    # check_name field on table ana.eligible_check
    KEY_CHECK_NAME = 'eligible_good_fdc_x100'
    API_ENDPOINT = '/api/amp/v1/fdc'


LFS_FIELDS = [
    'email',
    'fullname',
    'birth_place',
    'dob',
    'gender',
    'address_detail',
    'address_provinsi',
    'address_kabupaten',
    'address_kecamatan',
    'address_kelurahan',
    'marital_status',
    'mobile_phone_1',
    'close_kin_name',
    'close_kin_mobile_phone',
    'close_kin_relationship',
    'kin_name',
    'kin_mobile_phone',
    'job_type',
    'job_industry',
    'job_description',
    'company_name',
    'company_phone_number',
    'job_start',
    'payday',
    'monthly_income',
    'monthly_expenses',
    'total_current_debt',
    'bank_name',
    'bank_account_number',
    'loan_purpose',
    'last_education',
]

LFS_SPLIT_EMERGENCY_CONTACT_FIELDS = [
    'email',
    'fullname',
    'birth_place',
    'dob',
    'gender',
    'address_detail',
    'address_provinsi',
    'address_kabupaten',
    'address_kecamatan',
    'address_kelurahan',
    'marital_status',
    'mobile_phone_1',
    'job_type',
    'job_industry',
    'job_description',
    'company_name',
    'company_phone_number',
    'job_start',
    'payday',
    'monthly_income',
    'monthly_expenses',
    'total_current_debt',
    'bank_name',
    'bank_account_number',
    'loan_purpose',
    'last_education',
]

LONGFORM_FIELDS = [
    "email",
    "ktp",
    "fullname",
    "birth_place",
    "dob",
    "gender",
    "marital_status",
    "occupied_since",
    "home_status",
    "dependent",
    "mobile_phone_1",
    "address_street_num",
    "address_provinsi",
    "address_kabupaten",
    "address_kecamatan",
    "address_kelurahan",
    "address_kodepos",
    "close_kin_name",
    "close_kin_mobile_phone",
    "kin_relationship",
    "kin_name",
    "kin_mobile_phone",
    "job_type",
    "job_industry",
    "job_description",
    "company_name",
    "company_phone_number",
    "job_start",
    "payday",
    "last_education",
    "monthly_income",
    "monthly_expenses",
    "monthly_housing_cost",
    "total_current_debt",
    "bank_name",
    "bank_account_number",
    "loan_purpose",
    "loan_purpose_desc",
]


class OfflineBoothConst:

    TAG_NAME = 'is_offline_activation'
    SUCCESS_VALUE = 1


class AgentAssistedSubmissionConst:
    TAG_NAME = 'is_agent_assisted_submission'
    SUCCESS_VALUE = 1

    TOKEN_EXPIRE_HOURS = 12


class GeneralMessageResponseShortForm:

    key_name_flag = 'flag'
    key_name_message = 'message'

    flag_not_allowed_reapply_for_shortform = 'not_allowed_reapply_for_shortform'
    message_not_allowed_reapply_for_shortform = (
        'Maaf, terjadi kesalahan sistem, Silakan hubungi CS JULO untuk tuntaskan hal ini, ya.'
    )


class SimilarityTextConst:

    # maximum threshold if the value is equal is 1.0
    GENDER_LIST_OCR = ['LAKI-LAKI', 'PEREMPUAN']
    KEY_THRESHOLD_GENDER = 'threshold_gender'
    KEY_THRESHOLD_PROVINCE = 'threshold_province'
    KEY_THRESHOLD_CITY = 'threshold_city'
    KEY_THRESHOLD_DISTRICT = 'threshold_district'
    KEY_THRESHOLD_VILLAGE = 'threshold_village'

    IS_CHECKED_REPOPULATE_ZIPCODE = 'is_checked_repopulate_zipcode'
    TAG_STATUS_IS_FAILED = 0


class ExpireDayForm:

    DEFAULT_EXPIRE_DAY = 90

    # For x105 and Good Score
    EXPIRE_DAY_105_GOOD_SCORE_NON_J1 = 3
    EXPIRE_DAY_105_NON_J1 = 14

    LIST_GOOD_SCORE = ['B-', 'B+', 'A-', 'A']

    KEY_105_TO_106 = 'x105_to_x106'
    KEY_120_TO_106 = 'x120_to_x106'
    KEY_127_TO_106 = 'x127_to_x106'
    KEY_155_TO_106 = 'x155_to_x106'

    LIST_KEYS_EXPIRY_DAY_BELOW_x105 = [
        KEY_105_TO_106,
    ]
    LIST_KEYS_EXPIRY_DAY_ABOVE_x105 = [KEY_120_TO_106, KEY_127_TO_106, KEY_155_TO_106]

    LIST_EXPIRE_DAY_J1_CONST = [
        DEFAULT_EXPIRE_DAY,
    ]


class MotherMaidenNameConst:

    KEY_APP_VERSION = 'app_version'
    KEY_APP_ID = 'app_id'
    KEY_IMPROPER_NAMES = 'improper_names'

    ERROR_MESSAGE = (
        'Yuk, perbaiki dan pastikan penulisan nama lengkap '
        'ibu kandung sesuai KTP yang bersangkutan.'
    )


class AdditionalMessagesSubmitApp:

    KEY_BANNER_URL = 'banner_url'
    KEY_ADDITIONAL_MESSAGE = 'additional_message'
