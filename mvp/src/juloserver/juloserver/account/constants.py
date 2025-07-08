from argparse import Namespace
from builtins import object


class AccountConstant(object):
    STATUS_CODE = Namespace(
        **{
            'inactive': 410,
            'active': 420,
            'active_in_grace': 421,
            'overlimit': 425,
            'suspended': 430,
            'deactivated': 431,
            'terminated': 432,
            'fraud_reported': 440,
            'application_or_friendly_fraud': 441,
            'scam_victim': 442,
            'fraud_soft_reject': 443,
            'fraud_suspicious': 450,
            'sold_off': 433,
            'account_deletion_on_review': 460,
            'consent_withdrawal_requested': 463,
            'consent_withdrawed': 464,
        }
    )

    CREDIT_LIMIT_REJECT_AFFORBABILITY_VALUE = 300000
    CREDIT_LIMIT_REJECT_J_STARTER_AFFORBABILITY_VALUE = 500000
    # Value in Percentage
    PGOOD_CUTOFF = 0.90
    PGOOD_CUTOFF_BELOW = 0.80
    PGOOD_BYPASS_CREDIT_MATRIX = 0.65
    CREDIT_LIMIT_ADJUSTMENT_FACTOR = 0.80
    CREDIT_LIMIT_ADJUSTMENT_FACTOR_GTE_PGOOD_CUTOFF = 1.00
    LOCKED_TRANSACTION_STATUS = (
        STATUS_CODE.inactive,
        STATUS_CODE.overlimit,
        STATUS_CODE.suspended,
        STATUS_CODE.deactivated,
        STATUS_CODE.terminated,
        STATUS_CODE.fraud_reported,
        STATUS_CODE.application_or_friendly_fraud,
        STATUS_CODE.fraud_suspicious,
        STATUS_CODE.scam_victim,
    )

    LIMIT_INCREASING_LOAN_STATUSES = (216, 217, 219, 250, 215)
    LIMIT_DECREASING_LOAN_STATUSES = (210,)
    DEFAULT_IS_PROVEN = False

    PROVEN_THRESHOLD_CALCULATION_PERCENTAGE = 0.80
    PROVEN_THRESHOLD_CALCULATION_LIMIT = 3000000
    UNLOCK_STATUS = (STATUS_CODE.active,)
    REACTIVATION_ACCOUNT_STATUS = (STATUS_CODE.suspended, STATUS_CODE.active_in_grace)
    NOT_SENT_TO_INTELIX_ACCOUNT_STATUS = (
        STATUS_CODE.inactive,
        STATUS_CODE.deactivated,
        STATUS_CODE.terminated,
        STATUS_CODE.sold_off,
    )
    UPDATE_CASHBACK_BALANCE_STATUS = (STATUS_CODE.active, STATUS_CODE.suspended)
    EMPTY_INFO_CARD_ACCOUNT_STATUS = (
        STATUS_CODE.suspended,
        STATUS_CODE.deactivated,
        STATUS_CODE.terminated,
        STATUS_CODE.fraud_reported,
        STATUS_CODE.application_or_friendly_fraud,
        STATUS_CODE.fraud_suspicious,
        STATUS_CODE.scam_victim,
    )
    FRAUD_REJECT_STATUS = (STATUS_CODE.terminated, STATUS_CODE.fraud_soft_reject)
    REVERIFICATION_TAB_STATUSES = (STATUS_CODE.fraud_soft_reject,)
    NO_CHANGE_BY_DPD_STATUSES = (
        STATUS_CODE.fraud_reported,
        STATUS_CODE.application_or_friendly_fraud,
        STATUS_CODE.scam_victim,
        STATUS_CODE.fraud_suspicious,
    )
    NOT_SENT_TO_DIALER_SERVICE_ACCOUNT_STATUS = (
        STATUS_CODE.inactive,
        STATUS_CODE.deactivated,
        STATUS_CODE.terminated,
        STATUS_CODE.sold_off,
    )


class TransactionType(object):
    SELF = "self"
    OTHER = "other"
    PPOB = "ppob"
    ECOMMERCE = "e-commerce"

    DEFUALT_TRANSACTION_TYPE = SELF


class VoidTransactionType(object):
    PPOB_VOID = "ppob_void"
    CREDIT_CARD_VOID = "credit_card_void"


class CreditMatrixType(object):
    JULO1 = "julo1"
    JULO_ONE_IOS = "julo1_ios"
    JULO1_PROVEN = "julo1_proven"
    JULO1_REPEAT_MTL = "julo1_repeat_mtl"
    JULO1_ENTRY_LEVEL = 'julo1_entry_level'
    JULOVER = 'julover'
    JULO1_LIMIT_EXP = 'julo1_limit_exp'
    JULO_STARTER = 'j-starter'


class AccountLimitSignal(object):
    FOREIGN_KEY_FIELDS = ['account_id', 'latest_affordability_history_id', 'latest_credit_score_id']
    NOT_ALLOW_UPDATE_FIELDS = ['cdate', 'udate', 'id']


class AccountStatus430CardColorDpd(object):
    FIVE_TO_TEN = '5-10'
    MORE_THAN_EQUAL_ELEVEN = '>=11'


class FeatureNameConst(object):
    ACCOUNT_STATUS_X430_COLOR = 'account_status_x430_color_setting'
    ACCOUNT_SELLOFF_CONFIG = 'account_selloff_configuration'


class ImageSource(object):
    ACCOUNT_PAYMENT = 'account payment'


class PaymentFrequencyType(object):
    DAILY = 'daily'
    MONTHLY = 'monthly'


class LimitRecalculation(object):
    NO_CHANGE = 0
    INCREASE = 1
    DECREASE = 2


class CreditLimitGenerationLog:
    SIMPLE_LIMIT = 'simple_limit'
    REDUCED_LIMIT = 'reduced_limit'
    LIMIT_ADJUSTMENT_FACTOR = 'limit_adjustment_factor'
    MAX_LIMIT_PRE_MATRIX = 'max_limit (pre-matrix)'
    SET_LIMIT_PRE_MATRIX = 'set_limit (pre-matrix)'


class DpdWarningColorTreshold:
    DEFAULT = -3


class LDDEReasonConst:
    LDDE_V1 = 'LDDE v1'
    LDDE_V2 = 'LDDE v2'
    Manual = 'Manual'


class AccountLookupNameConst(object):
    JULO1 = 'JULO1'


class AccountLockReason:
    INVALID_ACCOUNT_STATUS = '001'
    INVALID_ACCOUNT_STATUS_A = '001_A'
    NOT_PROVEN_ACCOUNT = '002'
    BALANCE_CONSOLIDATION = '003'
    CUSTOMER_SUSPENDED = '004'  # keep it as old data, will be deprecated
    PRODUCT_SETTING = '005'
    ENTRY_LEVEL_LIMIT = '006'
    CUSTOMER_TIER = '007'
    GTL_INSIDE = '008'
    DISBURSEMENT_LIMIT = '009'
    GTL_OUTSIDE = '010'
    INVALID_APPLICATION_STATUS = '011'
    NAME_IN_BANK_MISMATCH = '012'
    FRAUD_BLOCK = '013'
    QRIS_NOT_WHITELISTED = '014'

    @staticmethod
    def get_choices():
        from juloserver.graduation.services import get_customer_suspend_codes
        attrs = {
            key: value for key, value in vars(AccountLockReason).items()
            if isinstance(value, str) and not key.startswith('_')
        }
        all_values = list(attrs.values()) + get_customer_suspend_codes()
        return [(value, value) for value in all_values]


class AccountChangeReason:
    SWIFT_LIMIT_DRAINER = 'System - Blocked Swift Limit Drainer'
    SWIFT_LIMIT_DRAINER_RETURN = 'Returned blocked Swift Limit Drainer'
    PERMANENT_BLOCK_SWIFT_LIMIT_DRAINER = 'Permanent Block Swift Limit Drainer'
    TELCO_MAID_LOCATION = 'System - Blocked Telco Maid Location Feature'
    TELCO_MAID_LOCATION_RETURN = 'System - Unblocked Telco Maid Location Feature'
    EXCEED_DPD_THRESHOLD = 'Exceed DPD Threshold Account Transaction Block'


class RedisKey(object):
    ACCOUNT_TRANSACTION_LOCK = "LATE_FEE_ACT_TRX_LOCK:{}"


class CheckoutPaymentType:
    DEFAULT = 'DEFAULT'
    CASHBACK = 'CASHBACK'
    REFINANCING = 'REFINANCING'
    CHECKOUT = 'CHECKOUT'


class UserType:
    J1 = 'J1'
    JULOVERS = 'JULOVERS'
    JTURBO = 'JTURBO'


class LimitAdjustmentFactorConstant:
    HIGH_MIN_PGOOD = 0.63
    MEDIUM_MIN_PGOOD = 0.53
    LOW_MIN_PGOOD = 0.43
    HIGH_FACTOR = 1
    MEDIUM_FACTOR = 0.9
    LOW_FACTOR = 0.8


class AccountTransactionNotes:
    VoidRefinancing = 'Void Refinancing Correction'
    ReinputRefinancing = 'Reinput Refinancing Correction'


class AccountLookupName:
    JULO1 = 'JULO1'
    JULOSTARTER = 'JULOSTARTER'
    JULOIOS = 'JULO1IOS'
