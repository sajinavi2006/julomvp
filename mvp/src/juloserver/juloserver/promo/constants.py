DEFAULT_TIMEOUT_SECONDS = 60
DEFAULT_DATETIME_FORMAT = "%Y-%m-%d %H:%M:%S"
EXPIRE_PROMO_CMS_SEARCH_EXPIRY_DAYS_DEFAULT = 30


class PromoCodeVersion:
    V1 = 'v1' # version 1: create_promo_code_usage at loan 212
    V2 = 'v2' # version 2:create promo_code_usage at loan 210


class PromoCodeTypeConst:
    APPLICATION = 'application'
    LOAN = 'loan'

    CHOICES = (
        (APPLICATION, 'Application'),
        (LOAN, 'Loan'),
    )


class PromoCodeCriteriaConst:
    APPLICATION_PARTNER = 'application_partner'
    PRODUCT_LINE = 'product_line'
    CREDIT_SCORE = 'credit_score'
    LIMIT_PER_CUSTOMER = 'limit_per_customer'
    LIMIT_PER_PROMO_CODE = 'limit_per_promo_code'
    TRANSACTION_METHOD = 'transaction_method'
    MINIMUM_LOAN_AMOUNT = 'minimum_loan_amount'
    MINIMUM_TENOR = 'minimum_tenor'
    R_SCORE = 'recency_score'
    WHITELIST_CUSTOMERS = 'whitelist_customers'
    CHURN_DAY = 'churn_day'
    APPLICATION_APPROVED_DAY = 'application_approved_day'
    B_SCORE = 'b_score'

    CHOICES = (
        (LIMIT_PER_CUSTOMER, 'Limit per customer'),
        (LIMIT_PER_PROMO_CODE, 'Limit per promo code'),
        (APPLICATION_PARTNER, 'Application Partner'),
        (PRODUCT_LINE, 'Product line'),
        (CREDIT_SCORE, 'Credit score'),
        (TRANSACTION_METHOD, 'Transaction Method'),
        (MINIMUM_LOAN_AMOUNT, 'Minimum Loan Amount'),
        (MINIMUM_TENOR, 'Minimum Tenor'),
        (R_SCORE, 'R-Score'),
        (WHITELIST_CUSTOMERS, 'Whitelist customers'),
        (CHURN_DAY, 'Churn Day'),
        (APPLICATION_APPROVED_DAY, 'Application approved day'),
        (B_SCORE, 'B Score')
    )

    # After modifying this, please update Admin fields in PromoCodeCriteriaForm()
    VALUE_FIELD_MAPPING = {
        LIMIT_PER_CUSTOMER: {'limit', 'times'},
        LIMIT_PER_PROMO_CODE: {'limit_per_promo_code', 'times'},
        APPLICATION_PARTNER: {'partners'},
        PRODUCT_LINE: {'product_line_codes'},
        CREDIT_SCORE: {'credit_scores'},
        TRANSACTION_METHOD: {'transaction_method_ids', 'transaction_history'},
        MINIMUM_LOAN_AMOUNT: {'minimum_loan_amount'},
        MINIMUM_TENOR: {'minimum_tenor'},
        R_SCORE: {'r_scores'},
        WHITELIST_CUSTOMERS: {'whitelist_customers_file'},
        CHURN_DAY: {'min_churn_day', 'max_churn_day'},
        APPLICATION_APPROVED_DAY: {'min_days_before', 'max_days_before'},
        B_SCORE: {'b_score'}
    }

    OPTIONAL_VALUE_FIELDS = {'transaction_history'}

    PROMO_CRITERIA_EXPERIMENT_GROUP_MAPPING = {
        143: "model_A",
        144: "model_B",
    }

    WHITELIST_BATCH_SIZE = 2000


class PromoCodeTimeConst:
    ALL_TIME = ('all_time')
    DAILY = ('daily')
    CHOICES = (
        (ALL_TIME, 'All time'),
        (DAILY, 'Daily')
    )


class PromoCodeCriteriaTxnHistory:
    NONE = None
    NEVER = "never"
    EVER = "ever"

    CHOICE = (
        (NONE, "None"),
        (NEVER, "Never"),
        (EVER, "Ever"),
    )


class PromoCodeBenefitConst:
    FIXED_CASHBACK = 'fixed_cashback'
    CASHBACK_FROM_LOAN_AMOUNT = 'cashback_from_loan_amount'
    INSTALLMENT_DISCOUNT = 'installment_discount'
    CASHBACK_FROM_INSTALLMENT = 'cashback_from_installment'
    INTEREST_DISCOUNT = 'interest_discount'
    VOUCHER = 'voucher'
    FIXED_PROVISION_DISCOUNT = 'fixed_provision_discount'
    PERCENT_PROVISION_DISCOUNT = 'percent_provision_discount'
    CHOICES = (
        (FIXED_CASHBACK, 'Fixed Cashback'),
        (CASHBACK_FROM_LOAN_AMOUNT, 'Cashback From Loan Amount'),
        (CASHBACK_FROM_INSTALLMENT, 'Cashback From Installment'),
        (INSTALLMENT_DISCOUNT, 'Installment Discount'),
        (INTEREST_DISCOUNT, 'Interest Discount'),
        (VOUCHER, 'Voucher'),
        (FIXED_PROVISION_DISCOUNT, 'Fixed Provision Discount'),
        (PERCENT_PROVISION_DISCOUNT, 'Percent Provision Discount'),
    )

    # After modifying this, please update Admin fields in PromoCodeBenefitForm()
    VALUE_FIELD_MAPPING = {
        FIXED_CASHBACK: {'amount'},
        CASHBACK_FROM_LOAN_AMOUNT: {'percent', 'max_cashback'},
        INSTALLMENT_DISCOUNT: {'percent', 'duration'},
        CASHBACK_FROM_INSTALLMENT: {'percent', 'max_cashback'},
        INTEREST_DISCOUNT: {'percent', 'duration', 'max_amount'},
        VOUCHER: set(),
        FIXED_PROVISION_DISCOUNT: {'amount'},
        PERCENT_PROVISION_DISCOUNT: {'percentage_provision_rate_discount', 'max_amount'},
    }

    OPTIONAL_VALUE_FIELDS = {'max_amount'}

    PROMO_CODE_BENEFIT_V2_APPLIED_DURING_LOAN_CREATION = [
        FIXED_PROVISION_DISCOUNT,
        PERCENT_PROVISION_DISCOUNT,
        INTEREST_DISCOUNT,
    ]

    PROMO_CODE_BENEFIT_TYPE_V2_SUPPORT = [
        FIXED_CASHBACK,
        CASHBACK_FROM_LOAN_AMOUNT,
        VOUCHER,
        FIXED_PROVISION_DISCOUNT,
        PERCENT_PROVISION_DISCOUNT,
    ]


class PromoBenefitType:
    CASHBACK = 'cashback'
    INSTALLMENT_DISCOUNT = 'installment_discount'
    INTEREST_DISCOUNT = 'interest_discount'


class PromoCodeMessage:
    class ERROR:
        INVALID = "Kode promo sudah tidak berlaku"
        WRONG = "Kode promo yang kamu masukkan salah"  # doesn't exist
        USED = "Kode promo sudah digunakan"
        MINIMUM_LOAN_AMOUNT = "Transaksi {minimum_amount} untuk pakai promo ini"
        MINIMUM_TENOR = 'Kode promo ini berlaku pada tenor minimum {minimum_tenor} bulan'
        LIMIT_PER_PROMO_CODE = "Kode promo ini telah habis digunakan"
        WHITELIST_CUSTOMER = "Kamu tidak dapat menggunakan kode promo ini"
        CHURN_DAY = "Kamu tidak dapat menggunakan kode promo ini"
        APPLICATION_APPROVED_DAY = "Kode promo sudah tidak berlaku"
        INVALID_TRANSACTION_METHOD = "Invalid transaction method"
        PROMO_CODE_BENEFIT_NOT_SUPPORT = 'Promo code benefit not support'
        INVALID_B_SCORE = "kamu belum memenuhi kriteria"

    class BENEFIT:
        CASHBACK = "Kamu dapat cashback {amount}"
        INSTALLMENT_DISCOUNT = "Kamu dapat potongan cicilan {amount}"
        INTEREST_DISCOUNT = "Kamu dapat potongan bunga {amount}"
        VOUCHER = "Promo berhasil digunakan"
        FIXED_PROVISION_DISCOUNT = "Kamu dapat potongan provisi {amount}"
        PERCENT_PROVISION_DISCOUNT = "Kamu dapat potongan provisi persen {percentage}, {max_amount_note}"


class PromoPageConst:
    TNC_CASHBACK = 'tnc_cashback'
    TNC_INSTALLMENT_DISCOUNT = 'tnc_installment_discount'

    CHOICES = (
        (TNC_CASHBACK, 'Tnc for Cashback'),
        (TNC_INSTALLMENT_DISCOUNT, 'Tnc for Installment Discount'),
    )


class FeatureNameConst:
    PROMO_ENTRY_PAGE = 'promo_entry_page'
    PROMO_CODE_WHITELIST_CUST = 'promo_code_whitelist_cust'


class PromoCMSRedisConstant:
    PROMO_CMS_LIST = 'promo.cms.get_list'
    PROMO_CMS_DETAIL = 'promo.cms.get_detail.{}'
    REDIS_CACHE_TTL_SECONDS_DEFAULT = 604800  # total seconds in week


class PromoCMSCategory:
    ALL = 'semua'
    PARTICIPATE = 'diikuti'
    AVAILABLE = 'berlangsung'
    EXPIRED = 'berakhir'


class WhitelistCSVFileValidatorConsts:
    ALLOWED_EXTENSIONS = ["csv"]
    MAX_FILE_SIZE = 1024 * 1024 * 2.5  # 2.5 MB
