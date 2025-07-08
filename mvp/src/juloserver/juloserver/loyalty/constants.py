from juloserver.payment_point.constants import TransactionMethodCode, SepulsaProductType

DEFAULT_DAILY_REWARD_CONFIG = {
    "1": 10,
    "2": 10,
    "3": 10,
    "4": 10,
    "5": 10,
    "6": 10,
    "7": 10,
    "default": 10
}
DEFAULT_POINT_CONVERT_TO_RUPIAH = 1
BULK_SIZE_DEFAULT = 1000


class FeatureNameConst:
    MISSION_FILTER_CATEGORY = 'mission_filter_category'
    POINT_EXPIRE_REMINDER_CONFIGURATION = 'point_expire_reminder_configuration'
    POINT_CONVERT = 'point_convert'
    WHITELIST_LOYALTY_CUST = 'whitelist_loyalty_cust'
    POINT_REDEEM = 'point_redeem'
    DANA_TRANSFER_WHITELIST_CUST = 'loyalty_dana_transfer_whitelist_cust'
    FLOATING_ACTION_BUTTON = 'floating_action_button'
    LOYALTY_ENTRY_POINT = 'loyalty_entry_point'


class MissionConfigTargetUserConst:
    FTC = 'FTC'
    REPEAT = 'REPEAT'

    CHOICES = [
        (FTC, FTC),
        (REPEAT, REPEAT),
    ]


class MissionConfigReferenceTypeConst:
    TRANSACTION = 'transaction'
    REFERRAL = 'referral'
    CHOICES = [
        (TRANSACTION, TRANSACTION),
        (REFERRAL, REFERRAL),
    ]


class MissionCategoryConst:
    GENERAL = 'general'
    TRANSACTION = 'transaction'
    REFERRAL = 'referral'

    CHOICES = [
        (GENERAL, 'General'),
        (TRANSACTION, 'Transaction'),
        (REFERRAL, 'Referral'),
    ]


class MissionFilterCategoryConst:
    ALL_MISSIONS = 'Semua Misi'
    ON_GOING = 'Sedang Berjalan'
    COMPLETED = 'Selesai'
    EXPIRED = 'Kedaluwarsa'

    # Mission will be hidden after 30 days expired
    DEFAULT_MISSION_FILTER_EXPIRY_DAYS = 30

    FILTER_CATEGORY_MAPPING_MISSION_PROGRESS_STATUS = {
        ALL_MISSIONS: ['in_progress', 'completed', 'claimed', 'expired'],
        ON_GOING: ['in_progress'],
        COMPLETED: ['completed'],
        EXPIRED: ['expired'],
    }


class MissionCriteriaTypeConst:
    TARGET_USER = 'target_user'
    UTILIZATION_RATE = 'utilization_rate'
    WHITELIST_CUSTOMERS = 'whitelist_customers_file'

    TRANSACTION_METHOD = 'transaction_method'
    TENOR = 'tenor'
    MINIMUM_LOAN_AMOUNT = 'minimum_loan_amount'
    TRANSACTION_METHODS = 'transaction_methods'  # this field contains list(transaction_method)

    CHOICES = [
        (TARGET_USER, 'Target User'),
        (UTILIZATION_RATE, 'Utilization Rate'),
        (WHITELIST_CUSTOMERS, 'Whitelist Customers'),
        (TRANSACTION_METHOD, 'Transaction Method'),
        (TENOR, 'Tenor'),
        (MINIMUM_LOAN_AMOUNT, 'Minimum Loan Amount'),
    ]

    VALUE_FIELD_MAPPING = {
        TARGET_USER: {'target_user'},
        TRANSACTION_METHOD: {'transaction_method_id', 'categories'},
        TENOR: {'tenor'},
        MINIMUM_LOAN_AMOUNT: {'minimum_loan_amount'},
        UTILIZATION_RATE: {'utilization_rate'},
        TRANSACTION_METHODS: {'transaction_methods'},
        WHITELIST_CUSTOMERS: {
            'whitelist_customers_file',
            'duration',
            'upload_url',
            'download_url'
        }
    }

    OPTIONAL_VALUE_FIELDS = {
        'categories',
        'transaction_methods',
        'upload_url',
        'download_url',
        'status',
    }


class MissionTargetTypeConst:
    # For general
    RECURRING = 'recurring'

    # For transaction
    TOTAL_TRANSACTION_AMOUNT = 'total_transaction_amount'

    CHOICES = [
        (RECURRING, 'Recurring'),
        (TOTAL_TRANSACTION_AMOUNT, 'Total Transaction Amount')
    ]

    VALUE_FIELD_MAPPING = {
        RECURRING: {'recurring'},
        TOTAL_TRANSACTION_AMOUNT: {'total_transaction_amount'}
    }

    DEFAULT_VALUES = {
        RECURRING: 0,
        TOTAL_TRANSACTION_AMOUNT: 0
    }


class MissionCriteriaValueConst:
    TARGET_USER = 'target_user'
    UTILIZATION_RATE = 'utilization_rate'
    ALLOWED_EXTENSIONS = ['csv']
    MAX_FILE_SIZE = 1024 * 1024 * 2.5 #  2.5 MB
    WHITELIST_CUSTOMERS_REDIS_KEY = 'loyalty_whitelist_criteria_customers.{}'
    CUSTOMER_ID_LENGTH = 10
    CUSTOMER_ID_PREFIX = "1"

    # transaction_methods: {transaction_method_id: ..., categories: [...]}
    TRANSACTION_METHODS = 'transaction_methods'
    TRANSACTION_METHOD_ID = 'transaction_method_id'
    CATEGORIES = 'categories'

    TENOR = 'tenor'
    MINIMUM_LOAN_AMOUNT = 'minimum_loan_amount'


class MissionCriteriaWhitelistStatusConst:
    PROCESS = 'process'
    SUCCESS = 'success'


class MissionRewardTypeConst:
    FIXED = 'fixed'
    PERCENTAGE = 'percentage'
    MAX_POINTS = 'max_points'

    CHOICES = [
        (FIXED, 'Fixed'),
        (PERCENTAGE, 'Percentage')
    ]

    VALUE_FIELD_MAPPING = {
        FIXED: {'fixed'},
        PERCENTAGE: {'percentage', 'max_points'},
    }

    OPTIONAL_VALUE_FIELDS = {'max_points'}


class MissionProgressStatusConst:
    STARTED = 'started'
    IN_PROGRESS = 'in_progress'
    COMPLETED = 'completed'
    CLAIMED = 'claimed'
    EXPIRED = 'expired'
    DELETED = 'deleted'

    CHOICES = [
        (STARTED, STARTED),
        (IN_PROGRESS, IN_PROGRESS),
        (COMPLETED, COMPLETED),
        (CLAIMED, CLAIMED),
        (EXPIRED, EXPIRED),
        (DELETED, DELETED),
    ]

    ALLOWED_RESET_STATUSES = [COMPLETED, CLAIMED]

    PRIORITY_ORDER = {COMPLETED: 1, IN_PROGRESS: 2, STARTED: 3, CLAIMED: 4, EXPIRED: 5}


class MissionProgressChangeReasonConst:
    MISSION_CONFIG_EXPIRED = "mission_config_is_expired"
    MISSION_CONFIG_DELETED = "mission_config_is_deleted"


class PointHistoryChangeReasonConst:
    DAILY_CHECKING = 'daily_checking'
    BONUS_CHECKING = 'bonus_checking'
    MISSION_COMPLETED = 'mission_completed'
    EXPIRED = 'expired'
    POINT_REPAYMENT = 'point_repayment'
    GOPAY_TRANSFER = 'gopay_transfer'
    REFUNDED_GOPAY_TRANSFER = 'refunded_gopay_transfer'
    DANA_TRANSFER = 'dana_transfer'
    REFUNDED_DANA_TRANSFER = 'refunded_dana_transfer'

    CHOICES = [
        (DAILY_CHECKING, DAILY_CHECKING),
        (BONUS_CHECKING, BONUS_CHECKING),
        (MISSION_COMPLETED, MISSION_COMPLETED),
        (EXPIRED, EXPIRED),
    ]

    REASON_MAPPING = {
        DAILY_CHECKING: 'Poin Check-in Harian',
        BONUS_CHECKING: 'Poin Check-in Bonus',
        EXPIRED: 'Kedaluwarsa',
        POINT_REPAYMENT: 'Potongan Tagihan Cicilan {}',
        GOPAY_TRANSFER: "Gopay transfer",
        REFUNDED_GOPAY_TRANSFER: "Refunded gopay transfer",
        DANA_TRANSFER: "Dana transfer",
        REFUNDED_DANA_TRANSFER: "Refunded dana transfer",
    }


class PointHistoryPaginationConst:
    DEFAULT_PAGE_SIZE = 20
    PAGE_SIZE_QUERY_PARAM = 'page_size'
    MAX_PAGE_SIZE = 50


class DailyCheckinConst:
    STATUS_CLAIMED = 'claimed'
    STATUS_TODAY = 'today'
    STATUS_AVAILABLE = 'available'
    STATUS_LOCKED = 'locked'


class DailyCheckinMessageConst:
    ERROR_HAS_BEEN_CLAIMED = "Daily check-in point has been claimed"
    ERROR_DAILY_CHECK_IN_NOT_FOUND = "No daily_checkin was found"


class MissionMessageConst:
    ERROR_MISSION_CONFIG_NOT_FOUND = "Mission config not found"
    ERROR_MISSION_PROGRESS_NOT_FOUND = "Mission progress not found"


class AdminSettingDailyRewardErrorMsg:
    INVALID_FORMAT = 'Setting has to be json format'
    KEY_REQUIRED = 'Key default required in daily reward'
    INVALID_DATA_TYPE = 'Key should be digit'
    INVALID_DATA_CONDITION = 'Day has to be integer > 0 and <= max days reach bonus'
    INVALID_VALUE_TYPE = 'Value should be integer'


class PointEarningExpiryTimeMilestoneConst:
    """
        Expiry time milestones of point earning, each value contains:
            - month: month index that point earning will be expired
            - day: day index that point earning will be expired
            - duration: years after that point earning will be expired
    """
    FIRST_MILESTONE = {
        "month": 7,
        "day": 1,
        "duration": 1
    }
    SECOND_MILESTONE = {
        "month": 1,
        "day": 1,
        "duration": 2
    }

    MILESTONES = [FIRST_MILESTONE, SECOND_MILESTONE]


TRANSACTION_METHOD_MAPPING_SEPULSA_PRODUCT_TYPE = {
    TransactionMethodCode.DOMPET_DIGITAL.code: SepulsaProductType.EWALLET,
    TransactionMethodCode.PULSA_N_PAKET_DATA.code: SepulsaProductType.MOBILE,
    TransactionMethodCode.TRAIN_TICKET.code: SepulsaProductType.TRAIN_TICKET,
    TransactionMethodCode.PDAM.code: SepulsaProductType.PDAM,
    TransactionMethodCode.BPJS_KESEHATAN.code: SepulsaProductType.BPJS,
    TransactionMethodCode.PASCA_BAYAR.code: SepulsaProductType.MOBILE,
    TransactionMethodCode.LISTRIK_PLN.code: SepulsaProductType.ELECTRICITY,
}

MISSION_PROGRESS_TRACKING_FIELDS = ['status', 'recurring_number', 'reference_data', 'point_earning']


class PointRedeemReferenceTypeConst:
    REPAYMENT = 'repayment'
    GOPAY_TRANSFER = 'gopay_transfer'
    DANA_TRANSFER = 'dana_transfer'

    CHOICES = [
        (REPAYMENT, REPAYMENT),
    ]


class PointExchangeUnitConst:
    POINT = 'point'
    RUPIAH = 'rupiah'

    CHOICES = [
        (POINT, POINT),
        (RUPIAH, RUPIAH),
    ]

    class Message:
        CONVERT_RATE_INFO = '1 poin = Rp{convert_rate}'


class PointExpiredReminderConst:
    DEFAULT_REMINDER_DAYS = 30

    class Message:
        EXPIRY_INFO = '{} Poin kamu akan kedaluwersa pada {}'
        POINT_USAGE_INFO = ('Potongan berlaku di taginan cicilan terakhir sesuai '
                            'jumlah saldo cashback kamu')


class RedemptionMethodErrorMessage:
    UNAVAILABLE_METHOD = ('Pencairan point melalui metode ini untuk sementara tidak dapat '
                           'dilakukan')


class PointRepaymentErrorMessage(RedemptionMethodErrorMessage):
    NO_ACCOUNT_PAYMENT = ('Tidak bisa melakukan pembayaran tagihan karena belum ada jadwal '
                          'pembayaran')
    BLOCK_DEDUCTION_POINT = ('Mohon maaf, saat ini point tidak bisa digunakan karena program '
                             'keringanan')
    NOT_ENOUGH_POINT = 'Anda tidak memiliki cukup poin untuk dikurangi'
    OPERATIONAL_ERROR = 'Terdapat transaksi yang sedang dalam proses, Coba beberapa saat lagi.'


class PointTransferErrorMessage(RedemptionMethodErrorMessage):
    INVALID_NOMINAL_AMOUNT = 'Jumlah nominal tidak valid'
    INSUFFICIENT_AMOUNT = 'Jumlah nominal tidak mencukupi'
    GOPAY_TRANSFER_NOT_FOUND = 'Gopay transfer transaction not found'
    SERVICE_UNAVAILABLE = ('Mohon maaf, terjadi kendala dalam proses pengajuan pencairan point, '
                           'Silakan coba beberapa saat lagi')


class RedemptionMethodErrorCode:
    # General
    UNAVAILABLE_METHOD = 'unavailable_method'

    # Repayment
    NO_ACCOUNT_PAYMENT = 'no_account_payment'
    BLOCK_DEDUCTION_POINT = 'block_deduction_point'
    NOT_ENOUGH_POINT = 'not_enough_point'

    # Gopay/DANA
    INVALID_NOMINAL_AMOUNT = 'invalid_nominal_amount'
    INSUFFICIENT_AMOUNT = 'insufficient_amount'
    OPERATIONAL_ERROR = 'operational_error'
    GOPAY_SERVICE_ERROR = 'gopay_service_error'


ERROR_CODE_MESSAGE_MAPPING = {
    RedemptionMethodErrorCode.UNAVAILABLE_METHOD:
        RedemptionMethodErrorMessage.UNAVAILABLE_METHOD,
    RedemptionMethodErrorCode.INVALID_NOMINAL_AMOUNT:
        PointTransferErrorMessage.INVALID_NOMINAL_AMOUNT,
    RedemptionMethodErrorCode.INSUFFICIENT_AMOUNT:
        PointTransferErrorMessage.INSUFFICIENT_AMOUNT,
    RedemptionMethodErrorCode.NO_ACCOUNT_PAYMENT:
        PointRepaymentErrorMessage.NO_ACCOUNT_PAYMENT,
    RedemptionMethodErrorCode.BLOCK_DEDUCTION_POINT:
        PointRepaymentErrorMessage.BLOCK_DEDUCTION_POINT,
    RedemptionMethodErrorCode.NOT_ENOUGH_POINT:
        PointRepaymentErrorMessage.NOT_ENOUGH_POINT,
    RedemptionMethodErrorCode.OPERATIONAL_ERROR:
        PointRepaymentErrorMessage.OPERATIONAL_ERROR,
    RedemptionMethodErrorCode.GOPAY_SERVICE_ERROR:
        PointRepaymentErrorMessage.OPERATIONAL_ERROR,
}


class ReferenceTypeConst:
    EASY_INCOME_UPLOAD = 'easy_income_upload'

    REFERENCE_TYPE_CHOICES = [
        (EASY_INCOME_UPLOAD, "Easy Income Upload")
    ]


class MissionEntryPointTooltip:
    DAILY_CHECKIN = 'Check-In!'


class MissionStatusMessageConst:
    STARTED_MSG = "Ayo, mulai dan selesaikan misi ini!"
    IN_PROGRESS_MSG = {
        "default": "{overall_progress} misi selesai. Yuk, selesaikan!",
        MissionTargetTypeConst.RECURRING: "{current} dari {target} transaksi selesai. Yuk, selesaikan!",
        MissionTargetTypeConst.TOTAL_TRANSACTION_AMOUNT: "Selesaikan misi, tarik total {remaining}.",
    }
    COMPLETED_MSG = "Misi selesai, klaim poinmu sekarang!"
    CLAIMED_MSG = "Misi selesai, hadiah telah diklaim"
    EXPIRED_MSG = "Misi kedaluwarsa"

    MESSAGE_MAPPING = {
        MissionProgressStatusConst.STARTED: STARTED_MSG,
        MissionProgressStatusConst.IN_PROGRESS: IN_PROGRESS_MSG,
        MissionProgressStatusConst.COMPLETED: COMPLETED_MSG,
        MissionProgressStatusConst.CLAIMED: CLAIMED_MSG,
        MissionProgressStatusConst.EXPIRED: EXPIRED_MSG,
    }


class APIVersionConst:
    V1 = 1
    V2 = 2

    CHOICES = [
        (V1, 'V1'),
        (V2, 'V2'),
    ]
