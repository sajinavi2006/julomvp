from builtins import object
from typing import Set


class AccountPaymentCons(object):
    ACCOUNT_PAYMENT = 'account_payment'


class CheckoutRequestCons(object):
    ACTIVE = 'active'
    EXPIRED = 'expired'
    CANCELED = 'canceled'
    REDEEMED = 'redeemed'
    FINISH = 'finished'
    # PN purpose
    PAID_CHECKOUT = 'paid_checkout'


class RepaymentRecallPaymentMethod:
    GOPAY = 'gopay'
    GOPAY_TOKENIZATION = 'gopay_tokenization'
    BCA = 'bca'
    OVO = 'OVO'
    FASPAY = 'faspay'
    DOKU = 'doku'
    ONEKLIK_BCA = 'OneKlik BCA'
    OVO_TOKENIZATION = 'OVO_Tokenization'

    @classmethod
    def all(cls) -> Set[str]:
        return {cls.BCA, cls.GOPAY, cls.GOPAY_TOKENIZATION, cls.OVO}

    @classmethod
    def gopay_channels(cls) -> Set[str]:
        return {cls.GOPAY, cls.GOPAY_TOKENIZATION}


class FeatureNameConst:
    REPAYMENT_FAQ_SETTING = "repayment_faq_setting"
    CRM_CUSTOMER_DETAIL_TAB = "crm_customer_detail_tab"
    REINQUIRY_PAYMENT_STATUS = "reinquiry_payment_status"
    AUTOMATE_LATE_FEE_VOID = "automate_late_fee_void"
    EXCLUDE_GRAB_FROM_UPDATE_PAYMENT_STATUS = "exclude_grab_from_update_payment_status"


class LateFeeBlockReason:
    ACTIVE_PTP = "Has active PTP"


class CashbackClaimConst:
    STATUS_PENDING = 'Pending'
    STATUS_ELIGIBLE = 'Eligible to Claim'
    STATUS_CLAIMED = 'Claimed'
    STATUS_VOID = 'Void'
    STATUS_VOID_CLAIM = 'Void after Claim'
    STATUS_EXPIRED = 'Expired'

    CASHBACK_CLAIM_LOCK = 'cashback_claim_lock_{}'


REPAYMENT_RECALL_WAIT_TIME = 2  # hours
OLD_APP_VERSION = "8.19.0"


class AccountPaymentDueStatus:
    NOT_DUE = "NOT_DUE"
    DUE = "DUE"
    LATE = "LATE"
    PAID_ON_TIME = "PAID_ON_TIME"
    PAID_LATE = "PAID_LATE"
