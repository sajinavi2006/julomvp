from builtins import object
from collections import namedtuple

from juloserver.julo.product_lines import ProductLineCodes

from juloserver.payment_point.constants import TransactionMethodCode

FIREBASE_LOAN_STAUSES = [220]
PHONE_REGEX_PATTERN = r'^((08)|(628))(\d{8,12})$'
FORBIDDEN_LOAN_PURPOSES = ('Investasi saham / Forex / Crypto',)
DEFAULT_ANDROID_CACHE_EXPIRY_DAY = 1
# 20/24: hour
ROBOCALL_END_TIME = 20
PREFIX_LOAN_ROBOCALL_REDIS = 'loan_robocall_redis__'
DEFAULT_OTHER_PLATFORM_MONTHLY_INTEREST_RATE = 0.1
DEFAULT_LIST_SAVING_INFORMATION_DURATION = [1, 3, 6, 9]
DISPLAY_LOAN_CAMPAIGN_ZERO_INTEREST = 'Bunga 0%'
DISPLAY_LOAN_CAMPAIGN_JULO_CARE = 'Julo Care'
IS_NAME_IN_BANK_MISMATCH_TAG = 'is_name_in_bank_mismatch'
QUERY_LIMIT = 2000


DEFAULT_LOCK_PRODUCT_BOTTOM_SHEET_INFO = {
    "body": "Kamu tidak bisa melanjutkan transaksi karena produk ini terkunci",
    "title": "Kamu Belum Bisa Transaksi",
    "button": "Mengerti",
}


class ErrorCode(object):
    INELIGIBLE_GTL_INSIDE = 'INELIGIBLE_GTL_INSIDE'
    INELIGIBLE_GTL_OUTSIDE = 'INELIGIBLE_GTL_OUTSIDE'


class OneClickRepeatConst:
    ONE_CLICK_REPEAT_DISPLAYED_LOAN = 5
    REDIS_KEY_CLICK_REPEAT = 'click_rep:{}'
    REDIS_KEY_CLICK_REPEAT_V2 = 'click_rep_v2:{}'
    REDIS_KEY_CLICK_REPEAT_V3 = 'click_rep_v3"{}'
    REDIS_CACHE_TTL_DAY = 1
    INTERVAL_DAY = 90


class OneClickRepeatTransactionMethod:
    V1 = [TransactionMethodCode.SELF.code]
    V2 = [TransactionMethodCode.SELF.code, TransactionMethodCode.DOMPET_DIGITAL.code]
    V3 = [
        TransactionMethodCode.SELF.code,
        TransactionMethodCode.DOMPET_DIGITAL.code,
        TransactionMethodCode.LISTRIK_PLN.code,
        TransactionMethodCode.BPJS_KESEHATAN.code,
    ]


class LoanJuloOneConstant(object):
    MIN_LOAN_AMOUNT_THRESHOLD = 300000
    DBR_LOAN_AMOUNT_DEFAULT = 2_000_000
    MIN_LOAN_AMOUNT_EDUCATION = 50000
    MIN_lOAN_TRANSFER_AMOUNT = 10000
    MIN_LOAN_AMOUNT_HEALTHCARE = 100_000
    PRODUCT_LOCK_FEATURE_SETTING = 'julo_one_product_lock'
    PPOB_PRODUCT = 'ppob'
    TARIK_DANA = 'tarik_dana'
    KIRIM_DANA = 'kirim_dana'
    ECOMMERCE_PRODUCT = 'ecommerce'
    QRIS = 'qris'
    CREDIT_CARD = 'credit_card'
    CASH_MIN_DURATION_DAYS = 61
    MIN_LOAN_AMOUNT_SIMULATION = 300000
    MAX_LOAN_AMOUNT_SIMULATION = 15000000
    MAX_LOAN_DURATION_AMOUNT = 30000000
    NUMBER_TENURE = 4
    MIN_DURATION_SIMULATION = 3
    MAX_DURATION_SIMULATION = 8
    ORIGINATION_FEE_SIMULATION = 0.05
    INTEREST_SIMULATION = 0.04
    CASHBACK_SIMULATION = 0.02
    PHONE_NUMBER_BLACKLIST = 'phone_number_blacklist'
    ANDRROID_ID_BLACKLIST = 'android_id_blacklist'
    LOAN_DURATION_DEFAULT_INDEX = 2
    TRAIN_TICKET = 'tiket_kereta'
    PDAM = 'pdam'
    EDUCATION = 'education'
    BALANCE_CONSOLIDATION = 'balance_consolidation'
    HEALTHCARE = 'healthcare'
    INTERNET_BILL = 'internet_bill'
    DOMPET_DIGITAL = 'dompet_digital'
    JFINANCING = 'j_financing'
    PFM = 'pfm'  # personal finance management
    QRIS_1 = 'qris_1'
    MIN_NEW_PCT_THRESHOLD = 0.04
    TAG_CAMPAIGN = 'Cicilan Termurah'


class LoanTaxConst(object):
    DEFAULT_PRODUCT_LINE_CODES = [ProductLineCodes.J1]
    ADDITIONAL_FEE_TYPE = 'LOAN_TAX'


class LoanDigisignFeeConst:
    DIGISIGN_FEE_TYPE = 'LOAN_DIGISIGN_FEE'
    REGISTRATION_DUKCAPIL_FEE_TYPE = 'REGISTRATION_DUKCAPIL_FEE'
    REGISTRATION_FR_FEE_TYPE = 'REGISTRATION_FR_FEE'
    REGISTRATION_LIVENESS_FEE_TYPE = 'REGISTRATION_LIVENESS_FEE'

    @classmethod
    def digisign_plus_register_types(cls):
        return [
            cls.DIGISIGN_FEE_TYPE,
            cls.REGISTRATION_DUKCAPIL_FEE_TYPE,
            cls.REGISTRATION_FR_FEE_TYPE,
            cls.REGISTRATION_LIVENESS_FEE_TYPE,
        ]


class DisbursementAutoRetryConstant(object):
    PPOB_MAX_RETRIES = 3
    PPOB_WAITING_MINUTES = 15


class TransactionRiskyDecisionName:
    OTP_NEEDED = "OTP Needed"


class LoanFeatureNameConst(object):
    """
    Feature settings name for loan-related things
    """

    LOAN_TENURE_RECOMMENDATION = "loan_tenure_recommendation"
    TRANSACTION_RESULT_NOTIFICATION = "transaction_result_notification"
    TRANSACTION_METHOD_LIMIT = 'transaction_method_limit'
    AFPI_DAILY_MAX_FEE = 'AFPI_daily_max_fee'
    ONE_CLICK_REPEAT = 'one_click_repeat'
    NEW_CREDIT_MATRIX_PRODUCT_LINE_RETRIEVAL_LOGIC = (
        "new_credit_matrix_product_line_retrieval_logic"
    )
    LOAN_TENURE_ADDITIONAL_MONTH = "loan_tenure_additional_month"
    NEW_TENOR_BASED_PRICING = "new_tenor_based_pricing"
    QRIS_WHITELIST_ELIGIBLE_USER = 'qris_whitelist_eligible_user'
    QRIS_FAQ = 'qris_faq'
    QRIS_TENURE_FROM_LOAN_AMOUNT = "qris_tenure_from_loan_amount"
    ANA_TRANSACTION_MODEL = 'ana_transaction_model'
    QRIS_LOAN_ELIGIBILITY_SETTING = "qris_loan_eligibility_setting"
    APPENDING_QRIS_TRANSACTION_METHOD_HOME_PAGE = "appending_qris_transaction_method_home_page"
    QRIS_MULTIPLE_LENDER = "qris_multiple_lender"
    GLOBAL_CAP_PERCENTAGE = "global_cap_percentage"
    QRIS_ERROR_LOG = "qris_error_log"
    AVAILABLE_LIMIT_INFO = "available_limit_info"
    LOCK_PRODUCT_PAGE = "lock_product_page"
    QRIS_PROGRESS_BAR = "qris_progress_bar"
    AUTO_ADJUST_DUE_DATE = "auto_adjust_due_date"


class GoogleDemo(object):
    EMAIL_ACCOUNT = 'demo@julofinance.com'


class LimitUsagePromoMoneyChangeReason(object):
    SEP_2021 = "promo_cashback"
    OCT_2021 = "promo_cashback_oct_2021"


class LoanStatusChangeReason:
    ACTIVATED = "Loan activated"
    SWIFT_LIMIT_DRAINER = "System - Blocked Swift Limit Drainer"
    TELCO_MAID_LOCATION = "System - Blocked Telco Maid Location Feature"
    FRAUD_LOAN_BLOCK = "System - Blocked General Fraud Loan"
    INVALID_NAME_BANK_VALIDATION = "Reject Xfers E-wallet invalid name bank"
    RUN_OUT_OF_LENDER_BALANCE = "Run out of Lender Balance"


class LoanPurposeConst:
    PERPINDAHAN_LIMIT = 'Tukar Tambah Limit'
    BIAYA_KESEHATAN = 'Biaya Kesehatan'
    BELANJA_ONLINE = 'Belanja online'


class TimeZoneName:
    WIB = 'WIB'
    WIT = 'WIT'
    WITA = 'WITA'


class RobocallTimeZoneQueue:
    ROBOCALL_WIB = 'loan_robocall_wib'
    ROBOCALL_WIT = 'loan_robocall_wit'
    ROBOCALL_WITA = 'loan_robocall_wita'


class SMSStatus:
    DELIVERED = 'delivered'


class CustomerSegmentsZeroInterest:
    FTC = 'ftc'
    REPEAT = 'repeat'


class CampaignConst:
    ZERO_INTEREST = 'zero_interest'
    JULO_CARE = 'julo_care'

    # for FE locked-product page
    PRODUCT_LOCK_PAGE_FOR_MERCURY = "mercury_lock"


class LockedProductPageConst:
    @classmethod
    def all_page_names(cls):
        return [
            CampaignConst.PRODUCT_LOCK_PAGE_FOR_MERCURY,
        ]


class JuloCareStatusConst(object):
    PENDING = 'POLICY_PENDING'
    ACTIVE = 'POLICY_ACTIVE'
    REQUEST = 'POLICY_REQUEST'
    FAILED = 'POLICY_FAILED'


class FDCUpdateTypes:
    AFTER_LOAN_STATUS_x211 = 'after_loan_status_x211'
    DAILY_CHECKER = 'daily_checker'
    GRAB_DAILY_CHECKER = 'grab_daily_checker'
    # because of out date or inquiry_status = pending
    GRAB_STUCK_150 = 'grab_stuck_150'
    GRAB_SUBMIT_LOAN = 'grab_submit_loan'
    MERCHANT_FINANCING_INITIATE = 'merchant_financing_initiate'
    MERCHANT_FINANCING_SUBMIT_LOAN = 'merchant_financing_submit_loan'


class DBRConst(object):
    DEFAULT_INCOME_PERCENTAGE = 50
    DEFAULT_PRODUCT_LINE_IDS = [ProductLineCodes.J1, ProductLineCodes.DANA]
    DEFAULT_POPUP_BANNER = {
        "is_active": True,
        "bottom_sheet_name": "debt_ratio",
        "title": "Kamu Belum Bisa Transaksi",
        "banner": {
            "is_active": True,
            "url": "https://statics.julo.co.id/loan/3_platform_validation/ineligible.png",
        },
        "content": (
            "Transaksi ini berpotensi melanggar aturan OJK, yaitu tagihan per bulan tidak dapat "
            "melebihi {}% dari total pengasilanmu.<br><br>Kamu bisa bayar tagihanmu "
            "sebelumnya dengan klik <b>Bayar</b> atau pilih tenor yang lebih panjang, ya!"
        ),
        "additional_information": {
            "clickable_text": "di sini",
            "content": (
                "Kamu juga bisa update penghasilan bulanan kamu dengan meng-upload slip gaji "
                "terbarumu di sini"
            ),
            "is_active": True,
            "link": "https://r.julo.co.id/1mYI/MissionPayslip",
        },
        "buttons": [{"is_active": True, "title": "Kembali"}, {"is_active": True, "title": "Bayar"}],
    }
    # only used if FS is not active
    DEFAULT_PARAMETERS = {
        "whitelist": {"is_active": False, "list_application_ids": []},
        "ratio_percentage": DEFAULT_INCOME_PERCENTAGE,
        "popup_banner": DEFAULT_POPUP_BANNER,
        "product_line_ids": DEFAULT_PRODUCT_LINE_IDS,
        "is_active": False,
    }
    BUTTON_KEY = "buttons"
    PAY_BUTTON_TITLE = "Bayar"
    CONTENT_KEY = "content"
    LINK = "link"
    ADDITIONAL_INFORMATION = "additional_information"
    LINK_PLACEHOLDER = {
        "[token]": "token",
        "[self_bank_account]": "self_bank_account",
        "[transaction_type_code]": "transaction_type_code",
    }

    LOAN_DURATION = "LOAN_DURATION"
    LOAN_CREATION = "LOAN_CREATION"

    DBR_SOURCE = (
        (LOAN_DURATION, LOAN_DURATION),
        (LOAN_CREATION, LOAN_CREATION),
    )
    MONTHLY_SALARY_ROUNDING = 500_000
    MONTHLY_SALARY_ERROR = "Update gaji tidak dapat dilakukan"
    MONTHLY_SALARY_APPROVAL_NOTE = "created from DBR"


class GTLOutsideConstant:
    DEFAULT_THRESHOLD_GTE_LIMIT_PERCENT = 90
    DEFAULT_THRESHOLD_LTE_B_SCORE = 0.75
    DEFAULT_THRESHOLD_GT_LAST_DPD_FDC = 0
    DEFAULT_BLOCK_TIME_IN_HOURS = 24 * 14  # 14 days
    ACCEPTABLE_DATE_DIFFS = [4, 5]
    EXCLUDE_ORGANIZER_AFDC150 = 'AFDC150'
    DYNAMIC_PARAM_IN_ERROR_MESSAGE = '{{waiting_days}}'


class GTLChangeReason:
    GTL_OUTSIDE_TIME_EXPIRES = 'daily cronjob to expire gtl outside'
    GTL_MANUAL_UNBLOCK_INSIDE = 'manualy unblock gtl inside'


class LoanFailGTLReason:
    INSIDE = 'inside'
    OUTSIDE = 'outside'

    CHOICES = (
        (INSIDE, INSIDE),
        (OUTSIDE, OUTSIDE),
    )


class TransactionResultConst:
    """
    Constants used for Transaction Result Android-Page/API
    """

    deeplink_base = "julo://notification?deep_link_sub1="

    class Type:
        IMAGE_TEXT = "image_text"
        TEXT_NORMAL = "text_normal"
        TEXT_COPY = "text_copy"

    class Status:
        FAILED = "FAILED"
        SUCCESS = "SUCCESS"
        IN_PROGRESS = "IN_PROGRESS"

    DEEPLINK_MAPPING = {
        TransactionMethodCode.SELF.code: "{}{}".format(deeplink_base, "tarik_dana"),  # 1
        TransactionMethodCode.OTHER.code: "{}{}".format(deeplink_base, "kirim_dana"),  # 2
        TransactionMethodCode.PULSA_N_PAKET_DATA.code: "{}{}".format(
            deeplink_base, "pulsa_data"
        ),  # 3
        TransactionMethodCode.PASCA_BAYAR.code: "{}{}".format(
            deeplink_base, "kartu_pasca_bayar"
        ),  # 4
        TransactionMethodCode.DOMPET_DIGITAL.code: "{}{}".format(deeplink_base, "e-wallet"),  # 5
        TransactionMethodCode.LISTRIK_PLN.code: "{}{}".format(deeplink_base, "listrik_pln"),  # 6
        TransactionMethodCode.BPJS_KESEHATAN.code: "{}{}".format(
            deeplink_base, "bpjs_kesehatan"
        ),  # 7
        TransactionMethodCode.E_COMMERCE.code: "{}{}".format(deeplink_base, "e-commerce"),  # 8
        TransactionMethodCode.TRAIN_TICKET.code: "{}{}".format(deeplink_base, "train_ticket"),  # 11
        TransactionMethodCode.PDAM.code: "{}{}".format(deeplink_base, "pdam_home_page"),  # 12
        TransactionMethodCode.EDUCATION.code: "{}{}".format(deeplink_base, "education_spp"),  # 13
        TransactionMethodCode.HEALTHCARE.code: "{}{}".format(
            deeplink_base, "healthcare_main_page"
        ),  # 14
        TransactionMethodCode.QRIS_1.code: "{}{}".format(
            deeplink_base, "qris_main_page"
        ),  # 19
    }


class LoanErrorCodes:
    """
    Loan Error Codes for external systems & clients
    """

    ErrorType = namedtuple('ErrorType', ['code', 'name', 'message'])

    # transaction 0xx
    GENERAL_ERROR = ErrorType('er_000', 'GENERAL_ERROR', 'Something went wrong')

    # withdraw more than available limit
    LIMIT_EXCEEDED = ErrorType('er_001', 'LIMIT_EXCEEDED', 'Limit pinjaman melebihi limit tersedia')

    PRODUCT_LOCKED = ErrorType(
        'er_002',
        'PRODUCT_LOCKED',
        """Maaf, Anda tidak bisa menggunakan fitur ini.
        Silakan gunakan fitur lain yang tersedia di menu utama.""",
    )
    TRANSACTION_LIMIT_EXCEEDED = ErrorType(
        'er_003', 'TRANSACTION_LIMIT_EXCEEDED', 'Transaksi harian melebihi limit harian'
    )
    DUPLICATE_TRANSACTION = ErrorType('er_004', 'DUPLICATE_TRANSACTION', 'Transaksi sudah ada')
    ACCOUNT_UNAVAILABLE = ErrorType(
        'er_005', 'ACCOUNT_UNAVAILABLE', 'Akun sedang tidak tersedia atau terblokir sementara'
    )
    TRANSACTION_AMOUNT_EXCEEDED = ErrorType(
        'er_006', 'TRANSACTION_AMOUNT_EXCEEDED', 'Lebih dari maximum Transaksi'
    )
    TRANSACTION_AMOUNT_TOO_LOW = ErrorType(
        'er_007', 'TRANSACTION_AMOUNT_TOO_LOW', 'Transaksi dibawah minimum set'
    )

    # qris 9xx
    QRIS_LINKAGE_NOT_ACTIVE = ErrorType('er_900', 'QRIS_LINKAGE_NOT_ACTIVE', 'Akun belum terhubung')
    NO_LENDER_AVAILABLE = ErrorType(
        'er_901',
        'NO_LENDER_AVAILABLE',
        """Kami membutuhkan waktu untuk mendapatkan pihak penyedia dana untuk memproses transaksi ini.
         Silakan coba lagi dalam beberapa waktu ke depan.""",
    )
    LENDER_NOT_SIGNED = ErrorType(
        'er_902',
        'LENDER_NOT_SIGNED',
        "Tanda tangani dokumen dari pihak Pemberi Dana agar kamu dapat lanjutkan transaksi QRIS!",
    )
    MERCHANT_BLACKLISTED = ErrorType(
        'er_903',
        'MERCHANT_IS_BLACKLISTED',
        'Transaksi tidak diperbolehkan pada Merchant ini untuk sementara'
    )


class DDWhitelistLastDigit:
    Method = namedtuple('Method', ['code', 'name'])
    ODD = Method(1, 'Odd')
    EVEN = Method(2, 'Even')
    NONE = Method(3, 'None')

    @classmethod
    def all(cls):
        return [
            cls.ODD,
            cls.EVEN,
            cls.NONE,
        ]

    @classmethod
    def all_code(cls):
        return [Wlast_digit.code for Wlast_digit in cls.all()]

    @classmethod
    def all_name(cls):
        return [Wlast_digit.name for Wlast_digit in cls.all()]

    @classmethod
    def choices(cls):
        return [(Wlast_digit.code, Wlast_digit.name) for Wlast_digit in cls.all()]


class LoanRedisKey:
    ANA_TRANSACTION_MODEL_COOLDOWN = 'ANA_TRANSACTION_MODEL_COOLDOWN_{customer_id}_{payload_hash}'


class LoanLogIdentifierType:
    CUSTOMER_ID = 'customer_id'
    APPLICATION_ID = 'application_id'
    TO_AMAR_USER_XID = 'to_amar_user_xid'

    CHOICES = (
        (CUSTOMER_ID, CUSTOMER_ID),
        (APPLICATION_ID, APPLICATION_ID),
        (TO_AMAR_USER_XID, TO_AMAR_USER_XID),
    )
