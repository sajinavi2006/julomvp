import logging
from builtins import object
from collections import namedtuple

from juloserver.account.constants import AccountConstant
from juloserver.loan.constants import LoanStatusChangeReason

logger = logging.getLogger(__name__)


class ApplicationStatusCodes(object):
    NOT_YET_CREATED = 0

    FORM_CREATED = 100
    FORM_CREATED_PARTNER = 1001
    FORM_PARTIAL = 105  # since application v3 all form data completed here
    # 1051 use for merchant financing after validation of historical transcation returns invalid
    MERCHANT_HISTORICAL_TRANSACTION_INVALID = 1051
    FORM_PARTIAL_EXPIRED = 106
    OFFER_REGULAR = 107
    JULO_STARTER_AFFORDABILITY_CHECK = 108
    JULO_STARTER_LIMIT_GENERATED = 109

    FORM_SUBMITTED = 110  # deprecated status since application v3
    FORM_SUBMITTED_PARTNER = 1201
    FORM_SUBMISSION_ABANDONED = 111
    APPLICATION_FLAGGED_FOR_FRAUD_SUSPICIOUS = 115

    DOCUMENTS_SUBMITTED = 120
    SCRAPED_DATA_VERIFIED = 121
    DOCUMENTS_VERIFIED = 122
    DOCUMENTS_VERIFIED_BY_THIRD_PARTY = 1220
    PRE_REJECTION = 123
    CALL_ASSESSMENT = 125
    PENDING_PARTNER_APPROVAL = 129

    VERIFICATION_CALLS_SUCCESSFUL = 124
    VERIFICATION_CALLS_SUCCESSFUL_BY_THIRD_PARTY = 1240
    APPLICANT_CALLS_ONGOING = 126
    TYPO_CALLS_UNSUCCESSFUL = 127
    CUSTOMER_IGNORES_CALLS = 128
    APPLICANT_CALLS_SUCCESSFUL = 130
    APPLICATION_RESUBMISSION_REQUESTED = 131
    APPLICATION_RESUBMITTED = 132
    APPLICATION_FLAGGED_FOR_FRAUD = 133
    APPLICATION_FLAGGED_FOR_SUPERVISOR = 134
    APPLICATION_DENIED = 135
    RESUBMISSION_REQUEST_ABANDONED = 136
    APPLICATION_CANCELED_BY_CUSTOMER = 137
    VERIFICATION_CALLS_ONGOING = 138
    VERIFICATION_CALLS_ONGOING_BY_THIRD_PARTY = 1380
    VERIFICATION_CALLS_EXPIRED = 139

    OFFER_MADE_TO_CUSTOMER = 140
    OFFER_ACCEPTED_BY_CUSTOMER = 141
    OFFER_DECLINED_BY_CUSTOMER = 142
    OFFER_EXPIRED = 143
    NAME_BANK_VALIDATION_FAILED = 144
    DIGISIGN_FAILED = 145
    DIGISIGN_FACE_FAILED = 147
    FORM_GENERATED = 148

    ACTIVATION_CALL_SUCCESS_AND_BANK_VALIDATE_ONGOING = 150
    ACTIVATION_AUTODEBET = 153

    WAITING_LIST = 155

    ACTIVATION_CALL_SUCCESSFUL = 160
    ACTIVATION_CALL_FAILED = 161

    LEGAL_AGREEMENT_RESUBMISSION_REQUESTED = 162
    LEGAL_AGREEMENT_SUBMITTED = 163
    NAME_VALIDATE_ONGOING = 164
    LENDER_APPROVAL = 165

    LEGAL_AGREEMENT_SIGNED = 170
    LEGAL_AGREEMENT_EXPIRED = 171
    LEGAL_AGREEMENT_SIGNED_AND_DP_PENDING = 172
    DOWN_PAYMENT_PAID = 173
    DOWN_PAYMENT_EXPIRED = 174
    NAME_VALIDATE_FAILED = 175
    KYC_IN_PROGRESS = 176

    FUND_DISBURSAL_ONGOING = 177
    BULK_DISBURSAL_ONGOING = 178
    BANK_NAME_CORRECTED = 179
    FUND_DISBURSAL_SUCCESSFUL = 180
    FUND_DISBURSAL_FAILED = 181

    CUSTOMER_ON_DELETION = 185
    CUSTOMER_DELETED = 186

    MISSING_EMERGENCY_CONTACT = 188

    CUSTOMER_ON_CONSENT_WITHDRAWAL = 183
    CUSTOMER_CONSENT_WITHDRAWED = 184

    PARTNER_APPROVED = 189
    LOC_APPROVED = 190
    JULO_STARTER_TURBO_UPGRADE = 191
    JULO_STARTER_UPGRADE_ACCEPTED = 192

    FACE_RECOGNITION_AFTER_RESUBMIT = 1311

    @classmethod
    def graveyards(cls):
        return (
            cls.APPLICATION_DENIED,
            cls.APPLICATION_FLAGGED_FOR_FRAUD,
            cls.FUND_DISBURSAL_FAILED,
            cls.FORM_SUBMISSION_ABANDONED
        )

    @classmethod
    def can_reapply(cls):
        return (
            cls.APPLICATION_DENIED,
            cls.APPLICATION_FLAGGED_FOR_FRAUD,
            cls.FUND_DISBURSAL_FAILED,
            cls.FORM_SUBMISSION_ABANDONED,
            cls.FORM_PARTIAL_EXPIRED,
            cls.LEGAL_AGREEMENT_EXPIRED,
            cls.OFFER_EXPIRED,
            cls.VERIFICATION_CALLS_EXPIRED,
            cls.ACTIVATION_CALL_FAILED,
            cls.FUND_DISBURSAL_SUCCESSFUL,
            cls.DOWN_PAYMENT_EXPIRED
        )

    @classmethod
    def reset_lender_counters(cls):
        return (
            cls.OFFER_ACCEPTED_BY_CUSTOMER,
            cls.LEGAL_AGREEMENT_SIGNED_AND_DP_PENDING,
            cls.ACTIVATION_CALL_SUCCESSFUL
        )

    @classmethod
    def in_progress_j1(cls):
        return (
            cls.DOCUMENTS_SUBMITTED,
            cls.SCRAPED_DATA_VERIFIED,
            cls.DOCUMENTS_VERIFIED,
            cls.CALL_ASSESSMENT,
            cls.VERIFICATION_CALLS_SUCCESSFUL,
            cls.APPLICANT_CALLS_SUCCESSFUL,
            cls.APPLICATION_RESUBMISSION_REQUESTED,
            cls.APPLICATION_RESUBMITTED,
            cls.OFFER_ACCEPTED_BY_CUSTOMER,
            cls.OFFER_DECLINED_BY_CUSTOMER,
            cls.DIGISIGN_FAILED,
            cls.DIGISIGN_FACE_FAILED,
            cls.ACTIVATION_CALL_SUCCESS_AND_BANK_VALIDATE_ONGOING,
            cls.NAME_VALIDATE_FAILED,
            cls.FACE_RECOGNITION_AFTER_RESUBMIT,
            cls.APPLICATION_FLAGGED_FOR_FRAUD_SUSPICIOUS,
        )

    @classmethod
    def eligible_for_emualtor_check_rejection(cls):
        return (
            cls.FORM_PARTIAL,
            cls.DOCUMENTS_SUBMITTED,
            cls.SCRAPED_DATA_VERIFIED,
            cls.VERIFICATION_CALLS_SUCCESSFUL
        )

    @classmethod
    def active_account(cls):
        return (
            cls.LOC_APPROVED,
            cls.JULO_STARTER_TURBO_UPGRADE,
        )

    @classmethod
    def rejection_statuses(cls):
        return (
            cls.APPLICATION_FLAGGED_FOR_FRAUD,
            cls.APPLICATION_DENIED,
        )


class LoanStatusCodes(object):
    DRAFT = 209
    INACTIVE = 210
    LENDER_APPROVAL = 211
    FUND_DISBURSAL_ONGOING = 212
    MANUAL_FUND_DISBURSAL_ONGOING = 213
    CANCELLED_BY_CUSTOMER = 216
    SPHP_EXPIRED = 217
    FUND_DISBURSAL_FAILED = 218
    # New status for Leadgen Webview for disbursement failed
    # from partner side
    DISBURSEMENT_FAILED_ON_PARTNER_SIDE = 2181
    LENDER_REJECT = 219
    CURRENT = 220
    LOAN_1DPD = 230
    LOAN_5DPD = 231
    LOAN_30DPD = 232
    LOAN_60DPD = 233
    LOAN_90DPD = 234
    LOAN_120DPD = 235
    LOAN_150DPD = 236
    LOAN_180DPD = 237
    LOAN_4DPD = 238
    LOAN_8DPD = 239
    RENEGOTIATED = 240
    HALT = 241
    PAID_OFF = 250
    SELL_OFF = 260

    TRANSACTION_FAILED = 215
    GRAB_AUTH_FAILED = 214
    LOAN_INVALIDATED = 2061
    LoanStatusesDPD = {
        CURRENT: 0,
        LOAN_1DPD: 1,
        LOAN_5DPD: 5,
        LOAN_30DPD: 30,
        LOAN_60DPD: 60,
        LOAN_90DPD: 90,
        LOAN_120DPD: 120,
        LOAN_150DPD: 150,
        LOAN_180DPD: 180,
        LOAN_4DPD: 4,
        LOAN_8DPD: 8,
    }

    @classmethod
    def mf_std_draft_loan(cls):
        return cls.DRAFT

    @classmethod
    def mf_std_need_skrtp_loan(cls):
        return cls.INACTIVE

    @classmethod
    def mf_std_verify_loan(cls):
        return cls.LENDER_APPROVAL, cls.FUND_DISBURSAL_ONGOING, cls.MANUAL_FUND_DISBURSAL_ONGOING

    @classmethod
    def mf_std_approved_loan(cls):
        return (
            cls.CURRENT,
            cls.LOAN_1DPD,
            cls.LOAN_5DPD,
            cls.LOAN_30DPD,
            cls.LOAN_60DPD,
            cls.LOAN_90DPD,
            cls.LOAN_120DPD,
            cls.LOAN_150DPD,
            cls.LOAN_180DPD,
            cls.LOAN_4DPD,
            cls.LOAN_8DPD,
            cls.RENEGOTIATED,
            cls.HALT,
        )

    @classmethod
    def mf_std_rejected_loan(cls):
        return cls.CANCELLED_BY_CUSTOMER, cls.LENDER_REJECT

    @classmethod
    def mf_std_paid_off_loan(cls):
        return cls.PAID_OFF

    @classmethod
    def mf_loan_status_in_progress(cls):
        return cls.DRAFT, cls.INACTIVE, cls.LENDER_APPROVAL, cls.FUND_DISBURSAL_ONGOING

    @classmethod
    def mf_loan_status_active(cls):
        return (
            cls.CURRENT,
            cls.LOAN_1DPD,
            cls.LOAN_5DPD,
            cls.LOAN_30DPD,
            cls.LOAN_60DPD,
            cls.LOAN_90DPD,
            cls.LOAN_120DPD,
            cls.LOAN_150DPD,
            cls.LOAN_180DPD,
            cls.LOAN_4DPD,
            cls.LOAN_8DPD,
            cls.RENEGOTIATED,
            cls.HALT,
        )

    @classmethod
    def mf_loan_status_done(cls):
        return cls.CANCELLED_BY_CUSTOMER, cls.PAID_OFF, cls.LENDER_REJECT

    @classmethod
    def loan_status_not_active(cls):
        return (cls.INACTIVE, cls.PAID_OFF, cls.SELL_OFF, cls.DRAFT)

    @classmethod
    def loan_status_active(cls):
        return (
            cls.CURRENT,
            cls.LOAN_1DPD,
            cls.LOAN_5DPD,
            cls.LOAN_30DPD,
            cls.LOAN_60DPD,
            cls.LOAN_90DPD,
            cls.LOAN_120DPD,
            cls.LOAN_150DPD,
            cls.LOAN_180DPD,
            cls.LOAN_4DPD,
            cls.LOAN_8DPD,
            cls.RENEGOTIATED,
            cls.HALT,
        )

    @classmethod
    def inactive_status(cls):
        return (
            cls.INACTIVE,
            cls.DRAFT
        )

    @classmethod
    def julo_one_loan_status(cls):
        return (
            cls.LENDER_APPROVAL,
            cls.FUND_DISBURSAL_ONGOING,
            cls.MANUAL_FUND_DISBURSAL_ONGOING,
            cls.FUND_DISBURSAL_FAILED,
            cls.LENDER_REJECT,
        )

    @classmethod
    def grab_above_90_dpd(cls):
        return (
            cls.CURRENT,
            cls.LOAN_1DPD,
            cls.LOAN_5DPD,
            cls.LOAN_30DPD,
            cls.LOAN_60DPD,
            cls.LOAN_90DPD,
            cls.LOAN_120DPD,
            cls.LOAN_150DPD,
            cls.LOAN_180DPD
        )

    @classmethod
    def grab_current_until_90_dpd(cls):
        return (
            cls.CURRENT,
            cls.LOAN_1DPD,
            cls.LOAN_5DPD,
            cls.LOAN_30DPD,
            cls.LOAN_60DPD,
            cls.LOAN_90DPD,
        )

    @classmethod
    def grab_current_until_180_dpd(cls):
        return (
            cls.CURRENT,
            cls.LOAN_1DPD,
            cls.LOAN_5DPD,
            cls.LOAN_30DPD,
            cls.LOAN_60DPD,
            cls.LOAN_90DPD,
            cls.LOAN_120DPD,
            cls.LOAN_150DPD,
            cls.LOAN_180DPD
        )

    @classmethod
    def train_ticket_pending_status(cls):
        return (
            cls.INACTIVE,
            cls.LENDER_APPROVAL,
            cls.FUND_DISBURSAL_ONGOING,
            cls.MANUAL_FUND_DISBURSAL_ONGOING,
        )

    @classmethod
    def train_ticket_cancel_status(cls):
        return (
            cls.CANCELLED_BY_CUSTOMER,
            cls.SPHP_EXPIRED,
        )

    @classmethod
    def train_ticket_failed_status(cls):
        return (
            cls.TRANSACTION_FAILED,
            cls.FUND_DISBURSAL_FAILED,
            cls.LENDER_REJECT,
        )

    @classmethod
    def grab_graveyard_status(cls):
        return (
            cls.INACTIVE,
            cls.CANCELLED_BY_CUSTOMER,
            cls.SPHP_EXPIRED,
            cls.LENDER_REJECT,
            cls.GRAB_AUTH_FAILED,
            cls.TRANSACTION_FAILED
        )

    @classmethod
    def fail_status(cls):
        return (
            cls.GRAB_AUTH_FAILED,
            cls.TRANSACTION_FAILED,
            cls.CANCELLED_BY_CUSTOMER,
            cls.SPHP_EXPIRED,
            cls.LENDER_REJECT,
        )

    @classmethod
    def J1_failed_loan_status(cls):
        return (
            cls.TRANSACTION_FAILED,
            cls.CANCELLED_BY_CUSTOMER,
            cls.SPHP_EXPIRED,
            cls.LENDER_REJECT,
        )

    @classmethod
    def pusdafil_loan_status(cls):
        return (
            cls.CURRENT,
            cls.LOAN_1DPD,
            cls.LOAN_5DPD,
            cls.LOAN_30DPD,
            cls.LOAN_60DPD,
            cls.LOAN_90DPD,
            cls.LOAN_120DPD,
            cls.LOAN_150DPD,
            cls.LOAN_180DPD,
            cls.LOAN_4DPD,
            cls.RENEGOTIATED,
            cls.HALT,
            cls.PAID_OFF,
            cls.SELL_OFF,
        )

    @classmethod
    def loan_status_due(cls):
        return (
            cls.LOAN_1DPD,
            cls.LOAN_5DPD,
            cls.LOAN_30DPD,
            cls.LOAN_60DPD,
            cls.LOAN_90DPD,
            cls.LOAN_120DPD,
            cls.LOAN_150DPD,
            cls.LOAN_180DPD,
        )

    @classmethod
    def julo_care_restricted_status(cls):
        return (
            cls.LENDER_APPROVAL,
            cls.FUND_DISBURSAL_ONGOING,
            cls.MANUAL_FUND_DISBURSAL_ONGOING,
            cls.FUND_DISBURSAL_FAILED,
        )

    @classmethod
    def loan_status_eligible_swift_limit(cls):
        return (
            cls.LENDER_APPROVAL,
            cls.FUND_DISBURSAL_ONGOING,
            cls.MANUAL_FUND_DISBURSAL_ONGOING,
            cls.CURRENT,
            cls.PAID_OFF,
        ) + cls.loan_status_due()

    @classmethod
    def failed_transaction_notification_status(cls):
        """
        Statuses that are considered failed for push notification
        """
        return (
            cls.TRANSACTION_FAILED,
            cls.CANCELLED_BY_CUSTOMER,
            cls.LENDER_REJECT,
        )

    @classmethod
    def transaction_notification_status(cls):
        """
        Statuses at which we want to notify customers
        """
        return (cls.CURRENT,) + cls.failed_transaction_notification_status()

    @classmethod
    def in_progress_status(cls):
        return [
            cls.INACTIVE,
            cls.LENDER_APPROVAL,
            cls.FUND_DISBURSAL_ONGOING,
            cls.FUND_DISBURSAL_FAILED,
        ]

    @classmethod
    def limit_not_subtracted_loan_status(cls):
        """
        Used for ana loan transaction model cases
        """
        return [
            *AccountConstant.LIMIT_INCREASING_LOAN_STATUSES,
            cls.DRAFT,
        ]

    @classmethod
    def fail_from_active_status(cls):
        return (
            cls.TRANSACTION_FAILED,
            cls.CANCELLED_BY_CUSTOMER,
        )


class PaymentStatusCodes(object):
    PAYMENT_NOT_DUE = 310
    PAYMENT_DUE_IN_3_DAYS = 311
    PAYMENT_DUE_TODAY = 312
    PAYMENT_DUE_IN_1_DAYS = 313

    PAYMENT_1DPD = 320
    PAYMENT_4DPD = 328
    PAYMENT_5DPD = 321
    PAYMENT_8DPD = 329
    PAYMENT_30DPD = 322
    PAYMENT_60DPD = 323
    PAYMENT_90DPD = 324
    PAYMENT_120DPD = 325
    PAYMENT_150DPD = 326
    PAYMENT_180DPD = 327

    PAID_ON_TIME = 330
    PAID_WITHIN_GRACE_PERIOD = 331
    PAID_LATE = 332
    # status using by paylater
    PAID_REFUND = 339
    PARTIAL_RESTRUCTURED = 334

    DOWN_PAYMENT_DUE = 340
    DOWN_PAYMENT_RECEIVED = 341
    DOWN_PAYMENT_ABANDONED = 342
    SELL_OFF = 360
    # after this hour uncalled bucket is active
    UNCALLED_PAYMENT_HOUR_SHIFT = 19

    @classmethod
    def paylater_paid_status_codes(cls):
        return (
            cls.PAID_ON_TIME,
            cls.PAID_WITHIN_GRACE_PERIOD,
            cls.PAID_LATE,
            cls.PAID_REFUND,
        )

    @classmethod
    def paid_status_codes(cls):
        return (
            cls.PAID_ON_TIME,
            cls.PAID_WITHIN_GRACE_PERIOD,
            cls.PAID_LATE,
            cls.SELL_OFF
        )

    @classmethod
    def waiver_exclude_status_codes(cls):
        return [
            cls.PAID_ON_TIME,
            cls.PAID_WITHIN_GRACE_PERIOD,
            # cls.PAYMENT_NOT_DUE,
            # cls.PAYMENT_DUE_IN_3_DAYS,
            # cls.PAYMENT_DUE_TODAY,
            # cls.PAYMENT_DUE_IN_1_DAYS
        ]

    @classmethod
    def all(cls):
        return (
            cls.PAYMENT_NOT_DUE,
            cls.PAYMENT_DUE_IN_3_DAYS,
            cls.PAYMENT_DUE_TODAY,
            cls.PAYMENT_DUE_IN_1_DAYS,
            cls.PAYMENT_1DPD,
            cls.PAYMENT_4DPD,
            cls.PAYMENT_5DPD,
            cls.PAYMENT_8DPD,
            cls.PAYMENT_30DPD,
            cls.PAYMENT_60DPD,
            cls.PAYMENT_90DPD,
            cls.PAYMENT_120DPD,
            cls.PAYMENT_150DPD,
            cls.PAYMENT_180DPD,
            cls.PAID_ON_TIME,
            cls.PAID_WITHIN_GRACE_PERIOD,
            cls.PAID_LATE,
            cls.DOWN_PAYMENT_DUE,
            cls.DOWN_PAYMENT_RECEIVED,
            cls.DOWN_PAYMENT_ABANDONED,
            cls.SELL_OFF)

    @classmethod
    def greater_5DPD_status_code(cls):
        return (
            cls.PAYMENT_5DPD,
            cls.PAYMENT_30DPD,
            cls.PAYMENT_60DPD,
            cls.PAYMENT_90DPD,
            cls.PAYMENT_120DPD,
            cls.PAYMENT_150DPD,
            cls.PAYMENT_180DPD
        )

    @classmethod
    def account_payment_status_codes(cls):
        return (
            cls.PAYMENT_NOT_DUE,
            cls.PAYMENT_DUE_IN_3_DAYS,
            cls.PAYMENT_DUE_TODAY,
            cls.PAYMENT_DUE_IN_1_DAYS,

            cls.PAYMENT_1DPD,
            cls.PAYMENT_4DPD,
            cls.PAYMENT_5DPD,
            cls.PAYMENT_8DPD,
            cls.PAYMENT_30DPD,
            cls.PAYMENT_60DPD,
            cls.PAYMENT_90DPD,
            cls.PAYMENT_120DPD,
            cls.PAYMENT_150DPD,
            cls.PAYMENT_180DPD,

            cls.PAID_ON_TIME,
            cls.PAID_WITHIN_GRACE_PERIOD,
            cls.PAID_LATE
        )

    @classmethod
    def paid_status_codes_without_sell_off(cls):
        return (
            cls.PAID_ON_TIME,
            cls.PAID_WITHIN_GRACE_PERIOD,
            cls.PAID_LATE,
        )

    @classmethod
    def not_paid_status_codes(cls):
        return (
            cls.PAYMENT_NOT_DUE,
            cls.PAYMENT_DUE_IN_3_DAYS,
            cls.PAYMENT_DUE_TODAY,
            cls.PAYMENT_DUE_IN_1_DAYS,
            cls.PAYMENT_1DPD,
            cls.PAYMENT_5DPD,
            cls.PAYMENT_30DPD,
            cls.PAYMENT_60DPD,
            cls.PAYMENT_90DPD,
            cls.PAYMENT_120DPD,
            cls.PAYMENT_150DPD,
            cls.PAYMENT_180DPD,
        )

    @classmethod
    def payment_not_late(cls):
        return (
            cls.PAYMENT_NOT_DUE,
            cls.PAYMENT_DUE_IN_3_DAYS,
            cls.PAYMENT_DUE_TODAY,
            cls.PAYMENT_DUE_IN_1_DAYS,
        )

    @classmethod
    def payment_late(cls):
        return (
            cls.PAYMENT_1DPD,
            cls.PAYMENT_4DPD,
            cls.PAYMENT_5DPD,
            cls.PAYMENT_8DPD,
            cls.PAYMENT_30DPD,
            cls.PAYMENT_60DPD,
            cls.PAYMENT_90DPD,
            cls.PAYMENT_120DPD,
            cls.PAYMENT_150DPD,
            cls.PAYMENT_180DPD
        )

    @classmethod
    def paid_dpd_plus_one(cls):
        return (
            cls.PAID_WITHIN_GRACE_PERIOD,
            cls.PAID_LATE,
        )


class JuloOneCodes(object):
    INACTIVE = 410
    ACTIVE = 420
    ACTIVE_IN_GRACE = 421
    OVERLIMIT = 425
    TERMINATED = 432
    DEACTIVATED = 431
    SUSPENDED = 430
    SOLD_OFF = 433
    FRAUD_REPORTED = 440
    APPLICATION_OR_FRIENDLY_FRAUD = 441
    SCAM_VICTIM = 442
    FRAUD_SOFT_REJECT = 443
    FRAUD_SUSPICIOUS = 450
    ACCOUNT_DELETION_ON_REVIEW = 460
    CONSENT_WITHDRAWAL_ON_REVIEW = 463
    CONSENT_WITHDRAWED = 464

    @classmethod
    def all(cls):
        return (
            cls.ACTIVE,
            cls.INACTIVE,
            cls.ACTIVE_IN_GRACE,
            cls.OVERLIMIT,
            cls.TERMINATED,
            cls.DEACTIVATED,
            cls.SUSPENDED,
            cls.FRAUD_REPORTED,
            cls.APPLICATION_OR_FRIENDLY_FRAUD,
            cls.SCAM_VICTIM,
            cls.FRAUD_SOFT_REJECT,
            cls.SOLD_OFF,
        )

    @classmethod
    def fdc_check(cls):
        return (
            cls.ACTIVE,
            cls.ACTIVE_IN_GRACE,
            cls.OVERLIMIT,
            cls.SUSPENDED,
            cls.FRAUD_REPORTED,
            cls.APPLICATION_OR_FRIENDLY_FRAUD,
            cls.SCAM_VICTIM
        )

    @classmethod
    def fraud_check(cls):
        return (
            cls.ACTIVE,
            cls.TERMINATED,
            cls.FRAUD_REPORTED,
            cls.APPLICATION_OR_FRIENDLY_FRAUD,
            cls.SCAM_VICTIM,
            cls.SUSPENDED,
            cls.ACTIVE_IN_GRACE

        )

    @classmethod
    def fraud_status_list(cls):
        return (
            cls.TERMINATED,
            cls.FRAUD_REPORTED,
            cls.APPLICATION_OR_FRIENDLY_FRAUD,
            cls.SCAM_VICTIM,
            cls.FRAUD_SOFT_REJECT
        )

    @classmethod
    def deleted(cls):
        return (
            cls.TERMINATED,
            cls.DEACTIVATED,
            cls.ACCOUNT_DELETION_ON_REVIEW
        )


class CreditCardCodes(object):
    CARD_OUT_OF_STOCK = 505
    CARD_APPLICATION_SUBMITTED = 510
    CARD_VERIFICATION_SUCCESS = 520
    CARD_ON_SHIPPING = 530
    CARD_APPLICATION_REJECTED = 525
    RESUBMIT_SELFIE = 523
    CARD_RECEIVED_BY_USER = 540
    CARD_VALIDATED = 545
    CARD_ACTIVATED = 580
    CARD_BLOCKED = 581
    CARD_UNBLOCKED = 582
    CARD_CLOSED = 583
    CARD_BLOCKED_WRONG_PIN = 584

    @classmethod
    def card_activation(cls):
        return (
            cls.CARD_OUT_OF_STOCK,
            cls.CARD_APPLICATION_SUBMITTED,
            cls.CARD_VERIFICATION_SUCCESS,
            cls.CARD_ON_SHIPPING,
            cls.CARD_APPLICATION_REJECTED,
            cls.RESUBMIT_SELFIE,
            cls.CARD_RECEIVED_BY_USER,
            cls.CARD_ACTIVATED,
            cls.CARD_VALIDATED
        )

    @classmethod
    def card_inactivation(cls):
        return (
            cls.CARD_BLOCKED,
            cls.CARD_CLOSED,
            cls.CARD_UNBLOCKED
        )

    @classmethod
    def all_card_statuses(cls):
        return {
            cls.CARD_OUT_OF_STOCK,
            cls.CARD_APPLICATION_SUBMITTED,
            cls.CARD_VERIFICATION_SUCCESS,
            cls.CARD_ON_SHIPPING,
            cls.CARD_APPLICATION_REJECTED,
            cls.RESUBMIT_SELFIE,
            cls.CARD_RECEIVED_BY_USER,
            cls.CARD_ACTIVATED,
            cls.CARD_VALIDATED,
            cls.CARD_BLOCKED,
            cls.CARD_CLOSED,
            cls.CARD_UNBLOCKED,
            cls.CARD_BLOCKED_WRONG_PIN,
        }

    @classmethod
    def status_eligible_resubmission(cls):
        return {
            cls.CARD_APPLICATION_REJECTED,
            cls.CARD_CLOSED,
        }


Status = namedtuple('Status', ['code', 'desc', 'app_label', 'change_reasons'])

reason_desc = {
    'KTP self': 'Foto KTP Pribadi',
    'KTP spouse': 'Foto KTP Suami/Istri',
    'KTP needed': 'Foto KTP Pribadi dan Suami/Istri',
    'KTP blurry': 'Foto KTP',
    'Salary doc needed': 'Foto Slip Gajih',
    'Salary doc not equal salary form': 'Foto Slip Gajih yang seusai',
    'Salary doc blurry': 'Foto Slip Gajih yang jelas',
}

Statuses = (

    ############################################################################
    # Application Statuses
    ############################################################################

    Status(
        code=ApplicationStatusCodes.FORM_CREATED,
        desc="Form created",
        app_label=None,
        change_reasons=()
    ),

    Status(
        code=ApplicationStatusCodes.FORM_CREATED_PARTNER,
        desc="Form created partner",
        app_label=None,
        change_reasons=()
    ),

    Status(
        code=ApplicationStatusCodes.FORM_PARTIAL,
        desc="Short form submitted",
        app_label=None,
        change_reasons=(
            'Short form submitted',
            'Success manual check liveness'
        )
    ),
    Status(
        code=ApplicationStatusCodes.FORM_PARTIAL_EXPIRED,
        desc="Short form expired",
        app_label=None,
        change_reasons=(
            'Form partial expired',
        )
    ),
    Status(
        code=ApplicationStatusCodes.OFFER_REGULAR,
        desc="Julo Starter offer to J1",
        app_label=None,
        change_reasons=(
            'Julo starter eligible j1',
        )
    ),
    Status(
        code=ApplicationStatusCodes.FORM_SUBMITTED,
        desc="Form submitted",
        app_label=None,
        change_reasons=(
            'Form submitted',
        )
    ),

    Status(
        code=ApplicationStatusCodes.FORM_SUBMITTED_PARTNER,
        desc="Form submitted partner",
        app_label=None,
        change_reasons=(
            'Form submitted',
        )
    ),

    Status(
        code=ApplicationStatusCodes.FORM_SUBMISSION_ABANDONED,
        desc="Form submission abandoned",
        app_label=None,
        change_reasons=(
            'Form submission abandoned',
        )
    ),
    Status(
        code=ApplicationStatusCodes.APPLICATION_FLAGGED_FOR_FRAUD_SUSPICIOUS,
        desc="Application flagged for fraud suspicious",
        app_label=None,
        change_reasons=(
            'Application flagged for fraud suspicious',
        )
    ),
    Status(
        code=ApplicationStatusCodes.DOCUMENTS_SUBMITTED,
        desc="Documents submitted",
        app_label=None,
        change_reasons=(
            'Documents submitted',
        )
    ),
    Status(
        code=ApplicationStatusCodes.SCRAPED_DATA_VERIFIED,
        desc="Scraped data verified",
        app_label=None,
        change_reasons=(
            'Phone data verified',
        )
    ),
    Status(
        code=ApplicationStatusCodes.DOCUMENTS_VERIFIED,
        desc="Documents verified",
        app_label=None,
        change_reasons=(
            'Document verified',
        )
    ),
    Status(
        code=ApplicationStatusCodes.DOCUMENTS_VERIFIED_BY_THIRD_PARTY,
        desc="Documents verified by third party",
        app_label=None,
        change_reasons=(
            'Document verified',
        )
    ),
    Status(
        code=ApplicationStatusCodes.PRE_REJECTION,
        desc="Pre-rejection",
        app_label=None,
        change_reasons=(
            'Automated test',
        )
    ),
    Status(
        code=ApplicationStatusCodes.PENDING_PARTNER_APPROVAL,
        desc="Pending approval by partner",
        app_label=None,
        change_reasons=(
            'Pending partner approval',
        )
    ),
    Status(
        code=ApplicationStatusCodes.VERIFICATION_CALLS_SUCCESSFUL,
        desc="Verification calls successful",
        app_label=None,
        change_reasons=(
            'PV Employer Verified',
            'Document Verified - Bank Scrape',
            'Document Verified - Income Doc Upload',
        )
    ),
    Status(
        code=ApplicationStatusCodes.VERIFICATION_CALLS_SUCCESSFUL_BY_THIRD_PARTY,
        desc="Verification calls successful by third party",
        app_label=None,
        change_reasons=(
            'PV Employer Verified',
            'Document Verified - Bank Scrape',
            'Document Verified - Income Doc Upload',
        )
    ),
    Status(
        code=ApplicationStatusCodes.APPLICANT_CALLS_ONGOING,
        desc="Verification calls successful",
        app_label=None,
        change_reasons=(
            'Applicant calls ongoing',
        )
    ),
    Status(
        code=ApplicationStatusCodes.TYPO_CALLS_UNSUCCESSFUL,
        desc="Typo calls unsuccessful",
        app_label=None,
        change_reasons=(
            'Unsuccessful calls',
        )
    ),
    Status(
        code=ApplicationStatusCodes.CUSTOMER_IGNORES_CALLS,
        desc="Applicants did not pick up calls consecutively",
        app_label=None,
        change_reasons=(
            'Customer did not pick up consecutively',
        )
    ),
    Status(
        code=ApplicationStatusCodes.APPLICANT_CALLS_SUCCESSFUL,
        desc="Applicant calls successful",
        app_label=None,
        change_reasons=(
            'PV Applicant Verified',
            'Merchant financing application',
        )
    ),
    Status(
        code=ApplicationStatusCodes.VERIFICATION_CALLS_ONGOING,
        desc="Verification calls ongoing",
        app_label=None,
        change_reasons=(
            'applicant not reachable-kami belum berhasil menghubungi anda',
            'employer not reachable-kami belum berhasil menghubungi kantor anda',
            'employer not willing to verify-kami belum berhasil menghubungi kantor anda',
        )
    ),
    Status(
        code=ApplicationStatusCodes.VERIFICATION_CALLS_ONGOING_BY_THIRD_PARTY,
        desc="Verification calls ongoing by third party",
        app_label=None,
        change_reasons=(
            'applicant not reachable-kami belum berhasil menghubungi anda',
            'employer not reachable-kami belum berhasil menghubungi kantor anda',
            'employer not willing to verify-kami belum berhasil menghubungi kantor anda',
        )
    ),
    Status(
        code=ApplicationStatusCodes.VERIFICATION_CALLS_EXPIRED,
        desc="Verification calls expired",
        app_label=None,
        change_reasons=(
            'Expired verification calls ongoing -- 138',
        )
    ),
    Status(
        code=ApplicationStatusCodes.APPLICATION_RESUBMISSION_REQUESTED,
        desc="Application re-submission requested",
        app_label=None,
        change_reasons=(
            'KTP needed-Foto KTP Anda yang terlihat jelas',
            'KTP blurry-Foto KTP buram. Mohon unggah foto KTP Anda yang terlihat jelas',
            'Salary doc needed-Slip gaji resmi dari bulan ini / bulan lalu yang terlihat jelas',
            'Salary doc blurry-Slip gaji buram. Mohon unggah slip gaji resmi dari bulan ini / bulan lalu yang terlihat jelas',
            'Selfie needed-Foto selfie Anda yang terlihat jelas',
            'Selfie blurry-Foto selfie buram. Mohon unggah foto selfie Anda yang terlihat jelas',
            # 'KK needed-Foto KK Anda yang terlihat jelas',
            'SIM needed-Foto SIM Anda yang terlihat jelas',
            'NPWP needed-Foto NPWP Anda yang terlihat jelas',
            'ID Pegawai needed-Foto ID Pegawai Anda yang terlihat jelas',
            'Mutasi Rekening needed-Foto Mutasi Rekening Anda yang terlihat jelas',
            'Informasi Iuran BPJS Ketenagakerjaan needed-Foto Informasi Iuran BPJS Ketenagakerjaan Anda yang terlihat jelas',
            'Surat Keterangan Kerja needed-Foto Surat Keterangan Kerja Anda yang terlihat jelas',
        )
    ),
    Status(
        code=ApplicationStatusCodes.APPLICATION_RESUBMITTED,
        desc="Application re-submitted",
        app_label=None,
        change_reasons=(
            'Application re-submitted',
        )
    ),
    Status(
        code=ApplicationStatusCodes.APPLICATION_FLAGGED_FOR_FRAUD,
        desc="Application flagged for fraud",
        app_label=None,
        change_reasons=(
            'Customer re-applying with different email',
            'Customer re-applying with different identity',
            'Data too closely-related to past application',
            'Suspicion based on spouse verification',
            'Suspicion based on employer verification',
            'Suspicion based on kin verification',
            'Suspicion based on employer verification',
            'Suspicion based on activation call',
            'Customer signature not matching',
            'Other fraud suspicions',
            'Liveness face and selfie face not matches'
            'Liveness face and KTP face not matches'
            'Liveness face and KTP face not matches + Liveness face and selfie face not matches',
        ),
    ),
    Status(
        code=ApplicationStatusCodes.APPLICATION_FLAGGED_FOR_SUPERVISOR,
        desc="Application flagged for supervisor",
        app_label=None,
        change_reasons=(
            'Application flagged for supervisor',
        )
    ),
    Status(
        code=ApplicationStatusCodes.APPLICATION_DENIED,
        desc="Application denied",
        app_label=None,
        change_reasons=(
            # These three need to be at the top
            # Used in workflows to block resubmission
            # If changed see workflows.
            'active loan exists',
            'negative payment history with JULO',
            'fraud report',
            'negative data in SD',
            'new phone-Mohon mengajukan kembali dalam 1/2 bulan mendatang menggunakan HP utama Anda yang telah aktif digunakan selama paling tidak 2 bulan terakhir ini. ',
            'age not met-Mohon mengajukan kembali saat usia Anda genap 21 tahun.',
            'not own smartphone-Mohon mengajukan kembali menggunakan HP utama Anda yang telah aktif digunakan selama paling tidak 2 bulan terakhir ini. ',
            'SD not available-Data Anda gagal masuk ke sistem kami. Mohon mengajukan kembali menggunakan HP utama Anda yang telah aktif digunakan selama paling tidak 2 bulan terakhir ini. ',
            'outside coverage area',
            'failed DV expired KTP-Mohon mengajukan kembali jika persyaratan eKTP terpenuhi.',
            'failed DV min income not met-Mohon mengajukan kembali saat penghasilan bersih Anda diatas Rp 3.000.000 per bulan.',
            'failed DV identity-(Terhambat pada verifikasi dokumentasi)',
            'failed DV income-(Terhambat pada verifikasi dokumentasi)',
            'failed DV other-(Terhambat pada verifikasi dokumentasi)',
            'job type blacklisted',
            'employer blacklisted',
            'facebook friends < 10',
            'failed PV employer-(Terhambat pada verifikasi kantor)',
            'failed PV spouse-(Terhambat pada verifikasi suami/ istri)',
            'failed PV applicant',
            'failed CA insuff income-Jika  mengajukan kembali kami sarankan untuk mengajukan dengan nominal pinjaman yang lebih kecil atau jangka waktu yang lebih panjang atau ajukan kembali saat penghasilan Anda meningkat di kemudian hari.',
            'failed bank transfer-(Transfer pencairan dana gagal)',
            'bank account not under own name-(Rekening bank untuk pencairan dana bukan atas nama Anda)',
            'cannot afford loan-Jika  mengajukan kembali kami sarankan untuk mengajukan dengan nominal pinjaman yang lebih kecil atau jangka waktu yang lebih panjang atau ajukan kembali saat penghasilan Anda meningkat di kemudian hari.',
            'grace period',
        )
    ),
    Status(
        code=ApplicationStatusCodes.RESUBMISSION_REQUEST_ABANDONED,
        desc="Resubmission request abandoned",
        app_label=None,
        change_reasons=(
            'Resubmission request abandoned',
        )
    ),
    Status(
        code=ApplicationStatusCodes.APPLICATION_CANCELED_BY_CUSTOMER,
        desc="Application canceled by customer",
        app_label=None,
        change_reasons=(
            'Customer requested to cancel',
        )
    ),
    Status(
        code=ApplicationStatusCodes.OFFER_MADE_TO_CUSTOMER,
        desc="Offer made to customer",
        app_label=None,
        change_reasons=(
            'Offer made to customer by agent',
        )
    ),
    Status(
        code=ApplicationStatusCodes.OFFER_ACCEPTED_BY_CUSTOMER,
        desc="Offer accepted by customer",
        app_label=None,
        change_reasons=(
            'Offer accepted by customer',
            'Offer auto-accepted by system',
        )
    ),
    Status(
        code=ApplicationStatusCodes.OFFER_DECLINED_BY_CUSTOMER,
        desc="Offer declined by customer",
        app_label=None,
        change_reasons=(
            'Offer declined by customer',
        )
    ),
    Status(
        code=ApplicationStatusCodes.OFFER_EXPIRED,
        desc="Offer expired",
        app_label=None,
        change_reasons=('Offer expired',)
    ),
    Status(
        code=ApplicationStatusCodes.DIGISIGN_FAILED,
        desc="Digisign failed",
        app_label=None,
        change_reasons=(
            'Digisign registration failed',
            'Digisign send document failed',
        )
    ),
    Status(
        code=ApplicationStatusCodes.DIGISIGN_FACE_FAILED,
        desc="Digisign face failed",
        app_label=None,
        change_reasons=('Digisign face registration fail',)
    ),
    Status(
        code=ApplicationStatusCodes.JULO_STARTER_AFFORDABILITY_CHECK,
        desc="Julo Starter Affordability Check",
        app_label=None,
        change_reasons=('Julo Starter Affordability Check',)
    ),
    Status(
        code=ApplicationStatusCodes.ACTIVATION_CALL_SUCCESS_AND_BANK_VALIDATE_ONGOING,
        desc="Activation call success and Bank validate ongoing",
        app_label=None,
        change_reasons=(
            'Name Validation Ongoing',
            'Credit approved',
            'Digisign registration verified',
            'Digisign send document verified',
        ),
    ),
    Status(
        code=ApplicationStatusCodes.ACTIVATION_CALL_SUCCESSFUL,
        desc="Activation call successful",
        app_label=None,
        change_reasons=(
            'Name Validation Ongoing',
            'Credit approved',
            'Digisign registration verified',
            'Digisign send document verified',
        )
    ),
    Status(
        code=ApplicationStatusCodes.ACTIVATION_CALL_FAILED,
        desc="Activation call failed",
        app_label=None,
        change_reasons=(
            'Activation call failed',
        )
    ),
    Status(
        code=ApplicationStatusCodes.LEGAL_AGREEMENT_RESUBMISSION_REQUESTED,
        desc="Legal Agreement docs resubmission requested",
        app_label=None,
        change_reasons=(
            'Signature not valid-tanda tangan ulang SPHP',
            'Voice recording not valid-rekam ulang perjanjian lisan SPHP'
        )
    ),
    Status(
        code=ApplicationStatusCodes.LEGAL_AGREEMENT_SUBMITTED,
        desc="Legal Agreement docs submitted",
        app_label=None,
        change_reasons=('legal agreement resubmitted',)
    ),
    Status(
        code=ApplicationStatusCodes.NAME_VALIDATE_ONGOING,
        desc="Name Validate Ongoing",
        app_label=None,
        change_reasons=('Name validate ongoing',)
    ),
    Status(
        code=ApplicationStatusCodes.LENDER_APPROVAL,
        desc="Lender approval",
        app_label=None,
        change_reasons=('Lender approval',)
    ),
    Status(
        code=ApplicationStatusCodes.LEGAL_AGREEMENT_SIGNED,
        desc="Legal agreement signed",
        app_label=None,
        change_reasons=('Legal agreement signed',)
    ),
    Status(
        code=ApplicationStatusCodes.LEGAL_AGREEMENT_EXPIRED,
        desc="Legal agreement expired",
        app_label=None,
        change_reasons=('Legal agreement expired',)
    ),
    Status(
        code=ApplicationStatusCodes.LEGAL_AGREEMENT_SIGNED_AND_DP_PENDING,
        desc="Legal agreement signed and dp pending",
        app_label=None,
        change_reasons=('Legal agreement signed & DP pending',)
    ),
    Status(
        code=ApplicationStatusCodes.DOWN_PAYMENT_PAID,
        desc="Down payment paid",
        app_label=None,
        change_reasons=(
            'Down payment paid',
        )
    ),
    Status(
        code=ApplicationStatusCodes.DOWN_PAYMENT_EXPIRED,
        desc="Down payment expired",
        app_label=None,
        change_reasons=(
            'Down payment expired',
        )
    ),
    Status(
        code=ApplicationStatusCodes.NAME_VALIDATE_FAILED,
        desc="Name validation failed",
        app_label=None,
        change_reasons=('Name validation failed',)
    ),
    Status(
        code=ApplicationStatusCodes.KYC_IN_PROGRESS,
        desc="KYC in progress",
        app_label=None,
        change_reasons=('Loan approved, account is created, and KYC in progress',)
    ),
    Status(
        code=ApplicationStatusCodes.FUND_DISBURSAL_ONGOING,
        desc="Fund disbursal ongoing",
        app_label=None,
        change_reasons=('Fund disbursal ongoing',)
    ),
    Status(
        code=ApplicationStatusCodes.BULK_DISBURSAL_ONGOING,
        desc="Bulk disbursal ongoing",
        app_label=None,
        change_reasons=('Bulk disbursal ongoing',)
    ),
    Status(
        code=ApplicationStatusCodes.FUND_DISBURSAL_SUCCESSFUL,
        desc="Fund disbursal successful",
        app_label=None,
        change_reasons=('Fund disbursal successful',)
    ),
    Status(
        code=ApplicationStatusCodes.FUND_DISBURSAL_FAILED,
        desc="Fund disbursal failed",
        app_label=None,
        change_reasons=(
            'Incorrect bank account details',
            'Fund transfer rejected by bank',
            'Other failure reason',
        )
    ),
    Status(
        code=ApplicationStatusCodes.PARTNER_APPROVED,
        desc="Loan application approved by partner",
        app_label=None,
        change_reasons=("Loan application approved by partner",)
    ),
    Status(
        code=ApplicationStatusCodes.LOC_APPROVED,
        desc="LOC application approved",
        app_label=None,
        change_reasons=("LOC application approved",)
    ),
    Status(
        code=ApplicationStatusCodes.CALL_ASSESSMENT,
        desc="Call Assessment",
        app_label=None,
        change_reasons=("Call Assessment",)
    ),
    Status(
        code=ApplicationStatusCodes.FACE_RECOGNITION_AFTER_RESUBMIT,
        desc="Face recognition after submit",
        app_label=None,
        change_reasons=('face_recognition_pass',)
    ),

    ############################################################################
    # Loan Statuses
    ############################################################################

    Status(
        code=LoanStatusCodes.INACTIVE,
        desc="Inactive",
        app_label="NON-AKTIF",
        change_reasons=("Loan requested by customer")
    ),
    Status(
        code=LoanStatusCodes.CANCELLED_BY_CUSTOMER,
        desc="customer cancelled on SPHP",
        app_label="JULO1",
        change_reasons=()
    ),
    Status(
        code=LoanStatusCodes.SPHP_EXPIRED,
        desc="SPHP Expired",
        app_label="JULO1",
        change_reasons=()
    ),
    Status(
        code=LoanStatusCodes.LENDER_APPROVAL,
        desc="Lender approval",
        app_label="JULO1",
        change_reasons=("Digital signature succeed")
    ),
    Status(
        code=LoanStatusCodes.FUND_DISBURSAL_ONGOING,
        desc="Fund disbursal ongoing",
        app_label="JULO1",
        change_reasons=("Loan approved by lender")
    ),
    Status(
        code=LoanStatusCodes.MANUAL_FUND_DISBURSAL_ONGOING,
        desc="Manual fund disbursal ongoing",
        app_label="JULO1",
        change_reasons=("Manual disbursement")
    ),
    Status(
        code=LoanStatusCodes.GRAB_AUTH_FAILED,
        desc="Grab API Failure Limit reached",
        app_label="GRAB",
        change_reasons=("Grab API Failure Limit reached")
    ),
    Status(
        code=LoanStatusCodes.FUND_DISBURSAL_FAILED,
        desc="Fund disbursal failed",
        app_label="JULO1",
        change_reasons=("Disbursement failed")
    ),
    Status(
        code=LoanStatusCodes.LENDER_REJECT,
        desc="Loan rejected by lender",
        app_label="JULO1",
        change_reasons=("Loan rejected by lender")
    ),
    Status(
        code=LoanStatusCodes.CURRENT,
        desc="Current",
        app_label="LANCAR",
        change_reasons=(LoanStatusChangeReason.ACTIVATED)
    ),
    Status(
        code=LoanStatusCodes.LOAN_1DPD,
        desc="1dpd",
        app_label="TERLAMBAT",
        change_reasons=()
    ),
    Status(
        code=LoanStatusCodes.LOAN_5DPD,
        desc="5dpd",
        app_label="TERLAMBAT",
        change_reasons=()
    ),
    Status(
        code=LoanStatusCodes.LOAN_30DPD,
        desc="30dpd",
        app_label="TERLAMBAT",
        change_reasons=()
    ),
    Status(
        code=LoanStatusCodes.LOAN_60DPD,
        desc="60dpd",
        app_label="TERLAMBAT",
        change_reasons=()
    ),
    Status(
        code=LoanStatusCodes.LOAN_90DPD,
        desc="90dpd",
        app_label="TERLAMBAT",
        change_reasons=()
    ),
    Status(
        code=LoanStatusCodes.LOAN_120DPD,
        desc="120dpd",
        app_label="TERLAMBAT",
        change_reasons=()
    ),
    Status(
        code=LoanStatusCodes.LOAN_150DPD,
        desc="150dpd",
        app_label="TERLAMBAT",
        change_reasons=()
    ),
    Status(
        code=LoanStatusCodes.LOAN_180DPD,
        desc="180dpd",
        app_label="TERLAMBAT",
        change_reasons=()
    ),
    Status(
        code=LoanStatusCodes.RENEGOTIATED,
        desc="Re-negotiated",
        app_label=None,
        change_reasons=()
    ),
    Status(
        code=LoanStatusCodes.HALT,
        desc="Halt",
        app_label=None,
        change_reasons=()
    ),
    Status(
        code=LoanStatusCodes.PAID_OFF,
        desc="Paid off",
        app_label="LUNAS",
        change_reasons=()
    ),
    Status(
        code=LoanStatusCodes.SELL_OFF,
        desc="Sell off",
        app_label="DIALIHKAN",
        change_reasons=()
    ),
    Status(
        code=LoanStatusCodes.TRANSACTION_FAILED,
        desc="Transaction failed",
        app_label="JULO1",
        change_reasons=("Transaction failed")
    ),

    ############################################################################
    # Payment Statuses
    ############################################################################

    Status(
        code=PaymentStatusCodes.PAYMENT_NOT_DUE,
        desc="Payment not due",
        app_label="Belum jatuh tempo",
        change_reasons=()
    ),
    Status(
        code=PaymentStatusCodes.PAYMENT_DUE_IN_3_DAYS,
        desc="Payment due in 3 days",
        app_label="Jatuh tempo sebentar lagi",
        change_reasons=()
    ),
    Status(
        code=PaymentStatusCodes.PAYMENT_DUE_IN_1_DAYS,
        desc="Payment due in 1 days",
        app_label="Jatuh tempo sebentar lagi",
        change_reasons=()
    ),
    Status(
        code=PaymentStatusCodes.PAYMENT_DUE_TODAY,
        desc="Payment due today",
        app_label="Jatuh tempo hari ini",
        change_reasons=()
    ),
    Status(
        code=PaymentStatusCodes.PAYMENT_1DPD,
        desc="1dpd",
        app_label="TERLAMBAT",
        change_reasons=()
    ),
    Status(
        code=PaymentStatusCodes.PAYMENT_5DPD,
        desc="5dpd",
        app_label="TERLAMBAT 5hr+",
        change_reasons=()
    ),
    Status(
        code=PaymentStatusCodes.PAYMENT_30DPD,
        desc="30dpd",
        app_label="TERLAMBAT 30hr+",
        change_reasons=()
    ),
    Status(
        code=PaymentStatusCodes.PAYMENT_60DPD,
        desc="60dpd",
        app_label="TERLAMBAT 60hr+",
        change_reasons=()
    ),
    Status(
        code=PaymentStatusCodes.PAYMENT_90DPD,
        desc="90dpd",
        app_label="TERLAMBAT 90hr+",
        change_reasons=()
    ),
    Status(
        code=PaymentStatusCodes.PAYMENT_120DPD,
        desc="120dpd",
        app_label="TERLAMBAT 120hr+",
        change_reasons=()
    ),
    Status(
        code=PaymentStatusCodes.PAYMENT_150DPD,
        desc="150dpd",
        app_label="TERLAMBAT 150hr+",
        change_reasons=()
    ),
    Status(
        code=PaymentStatusCodes.PAYMENT_180DPD,
        desc="180dpd",
        app_label="TERLAMBAT 180hr+",
        change_reasons=()
    ),
    Status(
        code=PaymentStatusCodes.PAID_ON_TIME,
        desc="Paid on time",
        app_label="Dibayar lunas, tepat waktu",
        change_reasons=()
    ),
    Status(
        code=PaymentStatusCodes.PAID_WITHIN_GRACE_PERIOD,
        desc="Paid within grace period",
        app_label="Dibayar lunas, dalam waktu tenggang",
        change_reasons=()
    ),
    Status(
        code=PaymentStatusCodes.PAID_LATE,
        desc="Paid late",
        app_label="Dibayar lunas, terlambat",
        change_reasons=()
    ),
    Status(
        code=PaymentStatusCodes.PAID_REFUND,
        desc="Paid refund",
        app_label="Dibayar lunas, lalu refund",
        change_reasons=()
    ),
    Status(
        code=PaymentStatusCodes.DOWN_PAYMENT_DUE,
        desc="Down payment due ",
        app_label="DP jatuh tempo",
        change_reasons=()
    ),
    Status(
        code=PaymentStatusCodes.DOWN_PAYMENT_RECEIVED,
        desc="Down payment received ",
        app_label="DP telah diterima",
        change_reasons=()
    ),
    Status(
        code=PaymentStatusCodes.DOWN_PAYMENT_ABANDONED,
        desc="Down payment abandoned ",
        app_label="DP tidak dibayarkan",
        change_reasons=()
    ),
    Status(
        code=PaymentStatusCodes.PARTIAL_RESTRUCTURED,
        desc="Payment partially paid before loan refinancing",
        app_label="Partial restruktur payment",
        change_reasons=()
    ),

    ############################################################################
    # Credit Card Statuses
    ############################################################################

    Status(
        code=CreditCardCodes.CARD_OUT_OF_STOCK,
        desc="Card is out of stock",
        app_label="Stok kartu kredit habis",
        change_reasons=()
    ),
    Status(
        code=CreditCardCodes.CARD_APPLICATION_SUBMITTED,
        desc="Card application submitted",
        app_label="Aplikasi kartu kredit diterima",
        change_reasons=()
    ),
    Status(
        code=CreditCardCodes.CARD_VERIFICATION_SUCCESS,
        desc="Card verification success",
        app_label="Aplikasi kartu kredit terverifikasi",
        change_reasons=()
    ),
    Status(
        code=CreditCardCodes.CARD_ON_SHIPPING,
        desc="Card on shipping",
        app_label="Kartu kredit dikirim ke user",
        change_reasons=()
    ),
    Status(
        code=CreditCardCodes.CARD_APPLICATION_REJECTED,
        desc="Card application rejected",
        app_label="Aplikasi kartu kredit ditolak",
        change_reasons=()
    ),
    Status(
        code=CreditCardCodes.RESUBMIT_SELFIE,
        desc="Resubmit selfie",
        app_label="User submit ulang selfie",
        change_reasons=()
    ),
    Status(
        code=CreditCardCodes.CARD_RECEIVED_BY_USER,
        desc="Card received by user",
        app_label="Kartu kredit diterima user",
        change_reasons=()
    ),
    Status(
        code=CreditCardCodes.CARD_ACTIVATED,
        desc="Card activated",
        app_label="Kartu kredit sudah diaktivasi",
        change_reasons=()
    ),
    Status(
        code=CreditCardCodes.CARD_BLOCKED,
        desc="Card blocked",
        app_label="Kartu kredit diblok",
        change_reasons=()
    ),
    Status(
        code=CreditCardCodes.CARD_CLOSED,
        desc="Card closed",
        app_label="Kartu kredit ditutup",
        change_reasons=()
    ),
    Status(
        code=CreditCardCodes.CARD_UNBLOCKED,
        desc="Card unblocked eligible",
        app_label="Kartu kredit eligible untuk unblock",
        change_reasons=()
    ),
    Status(
        code=CreditCardCodes.CARD_VALIDATED,
        desc="Card Validated",
        app_label="Aplikasi kartu kredit tervalidasi",
        change_reasons=()
    ),

    ############################################################################
    # Account Statuses
    ############################################################################

    Status(
        code=AccountConstant.STATUS_CODE.fraud_soft_reject,
        desc="Fraud Soft Reject",
        app_label="Gotham Soft Rejected Account",
        change_reasons=()
    ),
)


class StatusManager(object):

    @classmethod
    def get_or_none(cls, code):
        for status in Statuses:
            if status.code == code:
                logger.debug({
                    'status': 'found',
                    'status_code': status.code
                })
                return status
        logger.warn({
            'status': 'not_found',
            'status_code': code
        })
        return None

    @classmethod
    def dashed_change_reason_statuses(cls):
        return (
            ApplicationStatusCodes.LEGAL_AGREEMENT_RESUBMISSION_REQUESTED,
            ApplicationStatusCodes.APPLICATION_DENIED,
            ApplicationStatusCodes.APPLICATION_RESUBMISSION_REQUESTED,
            ApplicationStatusCodes.VERIFICATION_CALLS_ONGOING
        )
