from juloserver.julo.product_lines import ProductLineCodes

CASHBACK_FROZEN_MESSAGE = 'Saat ini Anda hanya bisa menggunakan metode pencairan Potongan ' \
                          'tagihan cicilan dikarenakan Anda memiliki pinjaman yang belum terbayar.'

BULK_SIZE_DEFAULT = 2000
PRODUCT_LINES_FOR_PAYMENT_AND_EXPIRY_CASHBACK = [
    ProductLineCodes.J1,
    ProductLineCodes.MTL1,
    ProductLineCodes.MTL2,
    ProductLineCodes.STL1,
    ProductLineCodes.STL2,
    ProductLineCodes.CTL1,
    ProductLineCodes.CTL2,
]

PRODUCT_LINES_FOR_PAYMENT_DPD = [
    ProductLineCodes.MTL1,
    ProductLineCodes.MTL2,
    ProductLineCodes.STL1,
    ProductLineCodes.STL2,
    ProductLineCodes.CTL1,
    ProductLineCodes.CTL2,
]


class CashbackChangeReason:
    LOAN_PAID_OFF = 'loan_paid_off'
    LOAN_PAID_OFF_VOID = 'loan_paid_off_void'
    LOAN_INITIAL = 'loan_initial'
    PAYMENT_ON_TIME = 'payment_on_time'
    USED_ON_PAYMENT = 'used_on_payment'
    PAYMENT_REVERSAL = 'payment_reversal'
    CASHBACK_REVERSAL = 'cashback_reversal'
    USED_TRANSFER = 'used_transfer'
    AGENT_FINANCE_ADJUSTMENT = 'agent_finance_adjustment'
    GOPAY_TRANSFER = 'gopay_transfer'
    REFUNDED_TRANSFER = 'refunded_transfer'
    REFUNDED_TRANSFER_GOPAY = 'refunded_transfer_gopay'
    CASHBACK_OVER_PAID = 'cashback_over_paid'
    CASHBACK_OVER_PAID_VOID = 'cashback_over_paid_void'
    OVERPAID_VERIFICATION_REFUNDED = 'overpaid_verification_refund'
    VERIFYING_OVERPAID = 'verifying_overpaid'
    SYSTEM_USED_ON_PAYMENT_EXPIRY_DATE = 'system_used_on_payment_expiry_date'
    CASHBACK_EXPIRED_END_OF_YEAR = 'cashback_expired_end_of_year'
    SYSTEM_USED_ON_PAYMENT_DPD_7 = 'system_used_on_payment_dpd_7'
    PROMO_REFERRAL = 'Promo_Referal'
    PROMO_REFERRAL_FRIEND = 'Promo_Referal_Friend'
    PROMO_REFERRALS = ('Promo_Referal', 'Promo_Referal_Friend')

    DELAYED_DISBURSEMENT = 'delayed_disbursement'


class OverpaidConsts:
    MINIMUM_AMOUNT = 20000

    class Statuses:
        UNPROCESSED = 'UNPROCESSED'
        PENDING = 'PENDING'
        ACCEPTED = 'ACCEPTED'
        REJECTED = 'REJECTED'

        PROCESSING_SUCCESS = "SUCCESS"
        PROCESSING_FAILED = "FAILED"

        # can't make cashback request if these exist:
        INELIGIBLE = [
            UNPROCESSED,
            REJECTED,
        ]

    class Reason:
        @classmethod
        def non_cashback_earned(cls):
            return [
                CashbackChangeReason.OVERPAID_VERIFICATION_REFUNDED,
                CashbackChangeReason.VERIFYING_OVERPAID
            ]

    class ImageType:
        PAYMENT_RECEIPT = "overpaid_receipt"

    class Message:
        # for old android apps without overpaid uploading feature
        CASHBACK_LOCKED = 'Silakan update aplikasi JULO terbaru untuk melanjutkan transaksi'


class CashbackExpiredConst:
    DEFAULT_REMINDER_DAYS = 30

    class Message:
        EXPIRY_INFO = 'Cashback <b>{expired_amount}</b> akan kadaluwarsa tanggal ' \
                      '<b>{expired_date}</b>.'


class CashbackMethodName:
    PAYMENT = 'payment'
    XENDIT = 'xendit'
    SEPULSA = 'sepulsa'
    GOPAY = 'gopay'
    TADA = 'tada'


class FeatureNameConst(object):
    CASHBACK_TEMPORARY_FREEZE = 'referral_cashback_freeze'


class ReferralCashbackEventType:
    CASHBACK_EARNED = 'cashback_earned'
    FIRST_REPAYMENT = 'first_repayment'
    CRONJOB = 'cronjob'


class ReferralCashbackAction:
    DO_NOTHING = 0
    FREEZE = 1
    UNFREEZE = 2
    UNFREEZE_FIRST_REPAYMENT = 3


class CashbackNewSchemeConst(object):
    ELIGIBLE_MINIMUM_ANDROID_VERSION = 2376
