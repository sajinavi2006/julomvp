from builtins import object, range
from datetime import date

from juloserver.cashback.constants import CashbackChangeReason

from .product_lines import ProductLineCodes  # noqa
from .statuses import ApplicationStatusCodes, LoanStatusCodes
from enum import Enum

APPLICATION_STATUS_CHANGE_CHOICES = (('previous_step_completed', 'Previous step completed'),)

DATA_CHECK_AGE_SEQ = 1
DATA_CHECK_OWN_PHONE_SEQ = 2
DATA_CHECK_SALARY_SEQ = 7
DATA_CHECK_JOB_TERM_SEQ = 16
DATA_CHECK_KTP_AREA_SEQ = 4
DATA_CHECK_KTP_DOB_SEQ = 5
DATA_CHECK_COMPANT_BL_SEQ = 15
DATA_CHECK_APPL_BL_SEQ = 11
DATA_CHECK_SPOUSE_NOT_DECLINED_SEQ = 12
DATA_CHECK_KIN_NOT_DECLINED_SEQ = 13
DATA_CHECK_SPOUSE_FOUND_SEQ = 31
DATA_CHECK_KIN_FOUND_SEQ = 32
DATA_CHECK_JOB_NOT_BLACKLIST = 71
DATA_CHECK_FB_FRIENDS_GT_50 = 72
DATA_CHECK_DOB_MATCH_FB_FORM = 73
DATA_CHECK_GENDER_MATCH_FB_FORM = 74
DATA_CHECK_EMAIL_MATCH_FB_FORM = 75
DATA_CHECK_HOME_ADDRESS_VS_GPS = 76
MAX_PAYMENT_EARNED_AMOUNT = 80000
MAX_PAYMENT_OVER_PAID = 100000
MAX_LATE_FEE_RATE = 0.2
ADVANCE_AI_BLACKLIST_CHECK_APP_STATUS = 105
ADVANCE_AI_ID_CHECK_APP_STATUS = 120
VOICE_CALL_SUCCESS_THRESHOLD = 18
BYPASS_CREDIT_SCORES_FROM_OTHER_PLATFORMS = ['A+', 'A', 'A-', 'B+', 'B-']

AXIATA_FEE_RATE = 0.05
AXIATA_LENDER_NAME = 'jtp'

TARGET_PARTNER = 'PARTNER'
TARGET_CUSTOMER = 'CUSTOMER'

MINIMUM_LOAN_DURATION_IN_DAYS = 61
MINIMUM_DAY_DIFF_LDDE_OLD_FLOW = 15
MINIMUM_DAY_DIFF_LDDE_v2_FLOW = 6

XID_LOOKUP_UNUSED_MIN_COUNT = 1000000
XID_MAX_COUNT = 13_000
VIRTUAL_ACCOUNT_SUFFIX_UNUSED_MIN_COUNT = 100000
REDIS_SET_CACHE_KEY_RETRY_IN_SECONDS = 0.02
REDIS_TIME_OUT_SECOND_DEFAULT = 30
LOCK_ON_REDIS = 'lock_on_redis'

URL_CARA_BAYAR = 'julo.co.id/r/sms'

JULO_ANALYTICS_DB = 'julo_analytics_db'

APP_STATUS_SKIP_PRIORITY = [
    ApplicationStatusCodes.SCRAPED_DATA_VERIFIED,
    ApplicationStatusCodes.DOCUMENTS_VERIFIED,
    ApplicationStatusCodes.VERIFICATION_CALLS_SUCCESSFUL,
    ApplicationStatusCodes.APPLICANT_CALLS_SUCCESSFUL,
    ApplicationStatusCodes.ACTIVATION_CALL_SUCCESS_AND_BANK_VALIDATE_ONGOING,
    ApplicationStatusCodes.ACTIVATION_CALL_SUCCESSFUL,
    ApplicationStatusCodes.LEGAL_AGREEMENT_SUBMITTED,
    ApplicationStatusCodes.LEGAL_AGREEMENT_SIGNED_AND_DP_PENDING,
    ApplicationStatusCodes.CALL_ASSESSMENT,
    ApplicationStatusCodes.APPLICATION_FLAGGED_FOR_FRAUD,
    ApplicationStatusCodes.APPLICATION_DENIED,
    ApplicationStatusCodes.APPLICATION_CANCELED_BY_CUSTOMER,
    ApplicationStatusCodes.LENDER_APPROVAL,
    ApplicationStatusCodes.LEGAL_AGREEMENT_SIGNED,
    ApplicationStatusCodes.FUND_DISBURSAL_SUCCESSFUL,
    ApplicationStatusCodes.FUND_DISBURSAL_FAILED,
    ApplicationStatusCodes.NAME_VALIDATE_FAILED,
]

APP_STATUS_WITH_PRIORITY = [
    ApplicationStatusCodes.DOCUMENTS_SUBMITTED,
    ApplicationStatusCodes.PRE_REJECTION,
    ApplicationStatusCodes.DOCUMENTS_VERIFIED_BY_THIRD_PARTY,
    ApplicationStatusCodes.VERIFICATION_CALLS_SUCCESSFUL_BY_THIRD_PARTY,
    ApplicationStatusCodes.APPLICATION_RESUBMITTED,
    ApplicationStatusCodes.APPLICATION_FLAGGED_FOR_SUPERVISOR,
    ApplicationStatusCodes.OFFER_ACCEPTED_BY_CUSTOMER,
    ApplicationStatusCodes.FORM_SUBMITTED,
    ApplicationStatusCodes.APPLICATION_RESUBMISSION_REQUESTED,
    ApplicationStatusCodes.VERIFICATION_CALLS_ONGOING,
    ApplicationStatusCodes.VERIFICATION_CALLS_ONGOING_BY_THIRD_PARTY,
    ApplicationStatusCodes.OFFER_MADE_TO_CUSTOMER,
    ApplicationStatusCodes.LEGAL_AGREEMENT_RESUBMISSION_REQUESTED,
    ApplicationStatusCodes.FORM_PARTIAL,
    ApplicationStatusCodes.FORM_SUBMISSION_ABANDONED,
    ApplicationStatusCodes.RESUBMISSION_REQUEST_ABANDONED,
    ApplicationStatusCodes.VERIFICATION_CALLS_EXPIRED,
    ApplicationStatusCodes.OFFER_DECLINED_BY_CUSTOMER,
    ApplicationStatusCodes.OFFER_EXPIRED,
    ApplicationStatusCodes.LEGAL_AGREEMENT_EXPIRED,
    ApplicationStatusCodes.ACTIVATION_CALL_FAILED,
    ApplicationStatusCodes.FORM_PARTIAL_EXPIRED,
    ApplicationStatusCodes.PENDING_PARTNER_APPROVAL,
    ApplicationStatusCodes.PARTNER_APPROVED,
    ApplicationStatusCodes.LOC_APPROVED,
    ApplicationStatusCodes.FUND_DISBURSAL_ONGOING,
    ApplicationStatusCodes.APPLICANT_CALLS_ONGOING,
    ApplicationStatusCodes.NAME_VALIDATE_ONGOING,
    ApplicationStatusCodes.DIGISIGN_FAILED,
    ApplicationStatusCodes.NAME_BANK_VALIDATION_FAILED,
]

APP_STATUS_SKIP_PRIORITY_NO_J1_NO_GRAB = [
    ApplicationStatusCodes.DOCUMENTS_VERIFIED,
    ApplicationStatusCodes.ACTIVATION_CALL_SUCCESSFUL,
    ApplicationStatusCodes.LEGAL_AGREEMENT_SUBMITTED,
    ApplicationStatusCodes.LEGAL_AGREEMENT_SIGNED_AND_DP_PENDING,
    ApplicationStatusCodes.CALL_ASSESSMENT,
    ApplicationStatusCodes.APPLICATION_FLAGGED_FOR_FRAUD,
    ApplicationStatusCodes.APPLICATION_DENIED,
    ApplicationStatusCodes.APPLICATION_CANCELED_BY_CUSTOMER,
    ApplicationStatusCodes.LENDER_APPROVAL,
    ApplicationStatusCodes.LEGAL_AGREEMENT_SIGNED,
    ApplicationStatusCodes.FUND_DISBURSAL_SUCCESSFUL,
    ApplicationStatusCodes.FUND_DISBURSAL_FAILED,
]

APP_STATUS_WITH_PRIORITY_NO_J1_NO_GRAB = [
    ApplicationStatusCodes.DOCUMENTS_SUBMITTED,
    ApplicationStatusCodes.PRE_REJECTION,
    ApplicationStatusCodes.DOCUMENTS_VERIFIED_BY_THIRD_PARTY,
    ApplicationStatusCodes.VERIFICATION_CALLS_SUCCESSFUL_BY_THIRD_PARTY,
    ApplicationStatusCodes.APPLICATION_FLAGGED_FOR_SUPERVISOR,
    ApplicationStatusCodes.FORM_SUBMITTED,
    ApplicationStatusCodes.APPLICATION_RESUBMISSION_REQUESTED,
    ApplicationStatusCodes.VERIFICATION_CALLS_ONGOING,
    ApplicationStatusCodes.VERIFICATION_CALLS_ONGOING_BY_THIRD_PARTY,
    ApplicationStatusCodes.OFFER_MADE_TO_CUSTOMER,
    ApplicationStatusCodes.LEGAL_AGREEMENT_RESUBMISSION_REQUESTED,
    ApplicationStatusCodes.FORM_PARTIAL,
    ApplicationStatusCodes.FORM_SUBMISSION_ABANDONED,
    ApplicationStatusCodes.RESUBMISSION_REQUEST_ABANDONED,
    ApplicationStatusCodes.VERIFICATION_CALLS_EXPIRED,
    ApplicationStatusCodes.OFFER_DECLINED_BY_CUSTOMER,
    ApplicationStatusCodes.OFFER_EXPIRED,
    ApplicationStatusCodes.LEGAL_AGREEMENT_EXPIRED,
    ApplicationStatusCodes.ACTIVATION_CALL_FAILED,
    ApplicationStatusCodes.FORM_PARTIAL_EXPIRED,
    ApplicationStatusCodes.PENDING_PARTNER_APPROVAL,
    ApplicationStatusCodes.PARTNER_APPROVED,
    ApplicationStatusCodes.LOC_APPROVED,
    ApplicationStatusCodes.FUND_DISBURSAL_ONGOING,
    ApplicationStatusCodes.APPLICANT_CALLS_ONGOING,
    ApplicationStatusCodes.NAME_VALIDATE_ONGOING,
    ApplicationStatusCodes.DIGISIGN_FAILED,
    ApplicationStatusCodes.NAME_BANK_VALIDATION_FAILED,
    ApplicationStatusCodes.WAITING_LIST,
    ApplicationStatusCodes.BANK_NAME_CORRECTED,
]

APP_STATUS_J1_WITH_PRIORITY = [ApplicationStatusCodes.OFFER_ACCEPTED_BY_CUSTOMER]

APP_STATUS_J1_SKIP_PRIORITY = [
    ApplicationStatusCodes.VERIFICATION_CALLS_SUCCESSFUL,
    ApplicationStatusCodes.APPLICANT_CALLS_SUCCESSFUL,
    ApplicationStatusCodes.ACTIVATION_CALL_SUCCESS_AND_BANK_VALIDATE_ONGOING,
    ApplicationStatusCodes.NAME_VALIDATE_FAILED,
    ApplicationStatusCodes.TYPO_CALLS_UNSUCCESSFUL,
    ApplicationStatusCodes.CUSTOMER_IGNORES_CALLS,
    ApplicationStatusCodes.ACTIVATION_AUTODEBET,
]

APP_STATUS_GRAB_WITH_PRIORITY = [ApplicationStatusCodes.APPLICATION_RESUBMITTED]

APP_STATUS_GRAB_SKIP_PRIORITY = [ApplicationStatusCodes.SCRAPED_DATA_VERIFIED]

APP_STATUS_PARTNERSHIP_AGENT_ASSISTED = [ApplicationStatusCodes.FORM_CREATED]

APP_STATUS_J1_AGENT_ASSISTED = [ApplicationStatusCodes.FORM_CREATED]

LOAN_STATUS = [
    LoanStatusCodes.CURRENT,
    LoanStatusCodes.RENEGOTIATED,
    LoanStatusCodes.PAID_OFF,
    LoanStatusCodes.MANUAL_FUND_DISBURSAL_ONGOING,
    LoanStatusCodes.INACTIVE,
    LoanStatusCodes.LENDER_APPROVAL,
    LoanStatusCodes.FUND_DISBURSAL_ONGOING,
    LoanStatusCodes.TRANSACTION_FAILED,
    LoanStatusCodes.CANCELLED_BY_CUSTOMER,
    LoanStatusCodes.FUND_DISBURSAL_FAILED,
]

LOAN_STATUS_J1 = [
    LoanStatusCodes.INACTIVE,
    LoanStatusCodes.CURRENT,
]

APPLICATION_STATUS_EXPIRE_PATH = [
    {
        'status_old': ApplicationStatusCodes.FORM_SUBMITTED,
        'status_to': ApplicationStatusCodes.FORM_SUBMISSION_ABANDONED,
        'days': 14,
    },
    {
        'status_old': ApplicationStatusCodes.VERIFICATION_CALLS_ONGOING,
        'status_to': ApplicationStatusCodes.VERIFICATION_CALLS_EXPIRED,
        'days': 14,
    },
    {
        'status_old': ApplicationStatusCodes.OFFER_MADE_TO_CUSTOMER,
        'status_to': ApplicationStatusCodes.OFFER_EXPIRED,
        'days': 3,
    },
    {
        'status_old': ApplicationStatusCodes.ACTIVATION_CALL_SUCCESSFUL,
        'status_to': ApplicationStatusCodes.LEGAL_AGREEMENT_EXPIRED,
        'days': 3,
        'target': TARGET_CUSTOMER,
    },
    {
        'status_old': ApplicationStatusCodes.OFFER_ACCEPTED_BY_CUSTOMER,
        'status_to': ApplicationStatusCodes.OFFER_EXPIRED,
        'days': 3,
        'target': TARGET_CUSTOMER,
    },
    {
        'status_old': ApplicationStatusCodes.OFFER_ACCEPTED_BY_CUSTOMER,
        'status_to': ApplicationStatusCodes.OFFER_EXPIRED,
        'days': 5,
        'target': TARGET_PARTNER,
    },
    {
        'status_old': ApplicationStatusCodes.ACTIVATION_CALL_SUCCESSFUL,
        'status_to': ApplicationStatusCodes.LEGAL_AGREEMENT_EXPIRED,
        'days': 3,
        'target': TARGET_PARTNER,
    },
]

RETRY_EMAIL_MINUTE = 30
RETRY_PN_MINUTE = 70
RETRY_SMS_J1_MINUTE = 120


class EmailTemplateConst(object):
    NOTIF_GRAB_250 = 'email_notif_grab_250'
    NOTIF_GRAB_330 = 'email_notif_grab_330'
    REMINDER_GRAB_DUE_TODAY = 'email_reminder_due_today_grab'
    REMINDER_DPD_GRAB = 'email_reminder_dpd_grab'
    SIGN_SPHP_MERCHANT_FINANCING = 'email_sign_sphp_merchant_finacing'


class NotPremiumAreaConst(object):
    MTL_MIN_AMOUNT = 2000000
    MTL_MAX_AMOUNT = 6000000
    PEDE1_MIN_AMOUNT = 2000000
    PEDE1_MAX_AMOUNT = 5000000
    MAX_LOAN_AMOUNT_BY_SCORE = {'A-': 6000000, 'B+': 5000000, 'B-': 4000000, 'C': 6000000}
    MAX_LOAN_DURATION_BY_SCORE = {'A-': 6, 'B+': 5, 'B-': 4, 'C': 6}


class FraudModelExperimentConst(object):
    MIN_AMOUNT = 1000000
    MAX_AMOUNT = 1000000
    MIN_DURATION = 2
    MAX_DURATION = 2
    INTEREST_RATE_MONTHLY = 0.07
    SCORE = 'B-'
    MOBMESSAGE = (
        'Peluang pengajuan Anda di-ACC cukup besar! Silakan pilih produk pinjaman '
        'di bawah ini & selesaikan pengajuannya.'
    )


class FalseRejectMiniConst(object):
    MIN_AMOUNT = 1000000
    MAX_AMOUNT = 1000000
    MIN_DURATION = 2
    MAX_DURATION = 2
    INTEREST_RATE_MONTHLY = 0.07
    SCORE = 'B-'
    MESSAGE = (
        'Peluang pengajuan Anda di-ACC cukup besar! Silakan pilih salah satu produk '
        'pinjaman di bawah ini & selesaikan pengajuannya. Tinggal sedikit lagi!'
    )
    MOBMESSAGE = (
        'Peluang pengajuan Anda di-ACC cukup besar! Silakan pilih produk pinjaman '
        'di bawah ini & selesaikan pengajuannya.'
    )


class MTLExtensionConst(object):
    MIN_AMOUNT = 1000000
    MIN_DURATION = 2
    MAX_DURATION = 4
    AFFORDABILITY = 540000
    MTL_MIN_AMOUNT = 1500000
    MTL_MAX_DURATION = 4


class JuloSTLMicro(object):
    MIN_AMOUNT = 500000
    MAX_AMOUNT = 1000000


class ScoreTag(object):
    C_FAILED_BINARY = "c_failed_binary"
    C_LOW_CREDIT_SCORE = "c_low_credit_score"
    C_FAILED_BLACK_LIST = "c_failed_blacklist_check"


class CollateralDropdown(object):
    COLLATERAL_TYPE_CAR = 'Mobil'
    COLLATERAL_TYPE_MOTOR = 'Motor'
    COLLATERAL_TYPE_CERTIFICATE = 'Sertifikat'
    CAR_BRAND_LIST = [
        'Daihatsu',
        'Datsun',
        'Ford',
        'Honda',
        'Hyundai',
        'Isuzu',
        'Kia',
        'Mazda',
        'Mercedes',
        'Mitsubishi',
        'Nissan',
    ]
    MOTOR_BRAND_LIST = ["Honda", "Yamaha", "Kawasaki", "Bajaj", "Vespa", "KTM"]
    CERTIFICATE_TYPE_LIST = ["Rumah", "Ruko", "Apartemen"]
    CAR_MIN_YEAR = 2000
    MOTOR_MIN_YEAR = 2000

    DROPDOWN_DATA = [
        {
            'type': COLLATERAL_TYPE_CAR,
            'model': CAR_BRAND_LIST,
            'year': {'min_year': CAR_MIN_YEAR, 'max_year': date.today().year},
        },
        {
            'type': COLLATERAL_TYPE_MOTOR,
            'model': MOTOR_BRAND_LIST,
            'year': {'min_year': MOTOR_MIN_YEAR, 'max_year': date.today().year},
        },
        {'type': COLLATERAL_TYPE_CERTIFICATE, 'model': CERTIFICATE_TYPE_LIST},
    ]


class SPHPConst(object):
    AGREEMENT_NUMBER = '1.JTF.201707'


class ExperimentConst(object):
    ITI_FIRST_TIME_CUSTOMER = ['ITIFTC121', 'ITIFTC132']
    BYPASS_CA_CALCULATION = 'ABCC'
    BYPASS_ITI122 = 'BypassITI122'
    BYPASS_ITI125 = 'BypassITI125'
    BYPASS_FT122 = 'BYPASSFT122'
    UNSET_ROBOCALL = 'UNSETROBOCALL'
    AGENT_CALL_BYPASS = 'AgentCallBypass'
    ROBOCALL_SCRIPT = 'ROBOCALLSCRIPT'
    COOTEK_AI_ROBOCALL_TRIAL = 'CootekAIRobocallTrial'
    COOTEK_AI_ROBOCALL_TRIAL_V3 = 'CootekAIRobocallTrialV3'
    COOTEK_AI_ROBOCALL_TRIAL_V4 = 'CootekAIRobocallTrialV4'
    COOTEK_AI_ROBOCALL_TRIAL_V5 = 'CootekAIRobocallTrialV5'
    REPEATED_HIGH_SCORE_ITI_BYPASS = 'RepeatedHighScoreITIBypass'
    ACBYPASS141 = 'ACBypass141'
    LOAN_DURATION_ITI = 'LoanDurationITI'
    PN_SCRIPT_EXPERIMENT = 'PNScriptExperiment'
    CEM_NEGATIVE_SCORE = 'CemNegativeScore'
    CEM_B2_B3_B4_EXPERIMENT = 'CeMB2B3B4EXPERIMENT'
    FALSE_REJECT_MINIMIZATION = 'FALSE_REJECT_MINIMIZATION'
    FRAUD_MODEL_105 = 'FRAUD_MODEL_105'
    ITI_LOW_THRESHOLD = 'LowThresholdITI'
    IS_OWN_PHONE_EXPERIMENT = 'Is_Own_Phone_Experiment'
    AFFORDABILITY_130_CALCULATION_TENURE = '130AffordabilityCalculationTenure'
    LOAN_GENERATION_CHUNKING_BY_100K = 'LoanGenerationChunkingBy100k'
    COOTEK_BL_PAYLATER = 'CootekBLPaylater'
    COLLECTION_NEW_DIALER_V1 = 'CollectionNewDialerV1'
    COOTEK_REVERSE_EXPERIMENT = 'Cootek Reverse Experiment'
    COOTEK_LATE_DPD_J1 = 'CootekLateDPDJ1'
    BONZA_REVERSE_EXPERIMENT = 'Bonza Reverse Experiment'
    COLL_DIALER_EXP2 = 'CollDialerExp2'
    BTTC_EXPERIMENT = 'BTTC_Experiment'
    LOAN_DURATION_DETERMINATION = 'LoanDurationDetermination'
    NEXMO_NUMBER_RANDOMIZER = 'NexmoNumberRandomizerExperiment'
    EXCELLENT_CUSTOMER_EXPERIMENT = 'excellent_customer_experiment'
    LOAN_DUE_DATE_EXPERIMENT = 'LoanDueDateExperiment'
    FINAL_CALL_V6_V7_EXPERIMENT = 'Final_Call_V6-V7_Experiment'
    CHECKOUT_EXPERIENCE_EXPERIMENT = 'checkout_experience_experiment'
    SHOPEE_SCORING = "ShopeeScoring"
    ACTIVATION_CALL_BYPASS = "ActivationCallBypass"
    B3_DISTRIBUTION_EXPERIMENT = "b3_distribution_experiment"
    JULO_STARTER_EXPERIMENT = "JuloStarterExperiment"
    PRIMARY_SMS_VENDORS_EXPERIMENT = 'PrimarySMSVendorsABTest'
    PRIMARY_OTP_SMS_VENDORS_EXPERIMENT = 'PrimaryOTPSMSVendorsABTest'
    OVO_NEW_FLOW_EXPERIMENT = 'OvoNewFlowExperiment'
    ROBOCALL_1WAY_VENDORS_EXPERIMENT = '1WayRobocallVendorsABTest'
    FRAUD_HOTSPOT_REVERSE_EXPERIMENT = 'FraudHotspotReverseExperiment'
    MYCROFT_HOLDOUT_EXPERIMENT = 'MycroftHoldoutExperiment'
    JOB_TYPE_MAHASISWA_BINARY = 'JobTypeMahasiswaBinary'
    PAYMENT_METHOD_EXPERIMENT = 'PaymentMethodExperiment'
    LIMIT_ADJUSTMENT_FACTOR = 'limit_adjustment_factor_experiment'
    SHOPEE_WHITELIST_EXPERIMENT = 'ShopeeWhitelistExperiment'
    FDC_IPA_BANNER_EXPERIMENT = 'FDCIPABannerExperiment'
    TOKO_SCORE_EXPERIMENT = 'TokoScoreExperiment'
    AUTODEBET_ACTIVATION_EXPERIMENT = 'AutodebetActivationExperiment'
    LEVERAGE_BANK_STATEMENT_EXPERIMENT = 'LeverageBankStatementExperiment'
    DUKCAPIL_FR = 'DukcapilFRExperiment'
    SHADOW_SCORE_EXPERIMENT = 'ShadowScoreExperiment'
    THREE_WAY_OTP_EXPERIMENT = '3wayOTPExperimentTest'
    KTP_OCR_EXPERIMENT = 'ktp_ocr_experiment'
    BPJS_X100_EXPERIMENT = 'BPJS_x100_experiment'
    OFFLINE_ACTIVATION_REFERRAL_CODE = 'offline_activation_referral_code'
    PN_PERMISSION_EXPERIMENT = 'notification_permission_experiment'
    LBS_130_BYPASS = 'lbs_130_bypass'
    LANNISTER_EXPERIMENT = 'LannisterCustomerSegment'
    FDC_IPA_BANNER_EXPERIMENT_V2 = 'FDCIPABannerExperimentV2'
    FDC_IPA_BANNER_EXPERIMENT_V3 = 'FDCIPABannerExperimentV3'
    SYNC_REGISTRATION_J360_SERVICES = 'sync_registration_j360_services'
    SMILE_MAGNIFEYE_LIVENESS_EXPERIMENT = 'smile_magnifeye_liveness_experiment'
    EMAIL_OTP_PREFILL_EXPERIMENT = 'EmailOtpPrefillExperiment'
    TAGIHAN_REVAMP_EXPERIMENT = 'TagihanRevampExperiment'
    HSFBP_INCOME_VERIFICATION = 'hsfbp_income_verification'
    MOTHER_NAME_VALIDATION = 'mother_name_validation'


class DisbursementStatus(object):
    FAILED = 'FAILED'
    PENDING = 'PENDING'
    COMPLETED = 'COMPLETED'
    PROCESSING = 'DISBURSING'
    INITIATED = 'INITIATED'
    INSUFICIENT_BALANCE = 'INSUFFICIENT BALANCE'
    INVALID_NAME_IN_BANK = 'NAME_INVALID'
    INVALID_BANK_ACCOUNT = 'INVALID BANK ACCOUNT'
    VALIDATION_SUCCESS = 'SUCCESS'
    NOT_FOUND = 'NOT FOUND'
    CHECKING_STATUSES = [FAILED, PENDING, PROCESSING]


class DisbursementMethod(object):
    METHOD_BCA = 'BCA'
    METHOD_XFERS = 'XFERS'
    METHOD_XENDIT = 'XENDIT'
    METHOD_MANUAL = 'MANUAL'
    METHOD_INSTAMONEY = 'INSTAMONEY'


class CashbackTransferConst(object):
    STATUS_REQUESTED = 'REQUESTED'
    STATUS_APPROVED = 'APPROVED'
    STATUS_REJECTED = 'REJECTED'
    STATUS_COMPLETED = 'COMPLETED'
    STATUS_PENDING = 'PENDING'
    STATUS_FAILED = 'FAILED'
    STATUS_VALIDATION_SUCCESS = 'SUCCESS'
    STATUS_INVALID = 'INVALID ACCOUNT'
    INITIATED = 'INITIATED'
    MIN_TRANSFER = 44000
    ADMIN_FEE = 4000
    METHOD_BCA = 'Bca'
    METHOD_XFERS = 'Xfers'
    METHOD_MANUAL = 'Manual'
    DEFAULT_METHOD = METHOD_XFERS
    partner_transfers = [METHOD_XFERS, METHOD_BCA, METHOD_MANUAL]
    FINAL_STATUSES = [STATUS_COMPLETED, STATUS_REJECTED]
    PROCESS_STATUSES = [STATUS_PENDING]
    FORBIDDEN_STATUSES = FINAL_STATUSES + PROCESS_STATUSES
    MEDIUM_TRANSFER = 74000


class PaymentConst(object):
    MAX_CHANGE_DUE_DATE_INTEREST = 200000


class VoiceTypeStatus(object):
    PAYMENT_REMINDER = "payment_reminder"
    PTP_PAYMENT_REMINDER = "ptp_payment_reminder"
    APP_CAMPAIGN = "application_campaign"
    COVID_CAMPAIGN = 'nexmo_robocall_covid_1'
    REFINANCING_REMINDER = 'refinancing_reminder'
    PAYMENT_REMINDER_DANA = "payment_reminder_dana"


class FeatureNameConst(object):
    """
    consider creating feature constants in your subapp
    since it's getting big
    """

    BYPASS_ITI_EXPERIMENT_122 = "bypass_iti_experiment_122"
    BYPASS_ITI_EXPERIMENT_125 = "bypass_iti_experiment_125"
    AUTO_POPULATE_EXPENSES = "auto_populate_expenses"
    ASSIGN_AGENT_DPD1_DPD30 = "assign_agent_dpd1_dpd30"
    ASSIGN_AGENT_DPD1_DPD29 = "assign_agent_dpd1_dpd29"
    ASSIGN_AGENT_DPD31PLUS = "assign_agent_dpd31plus"
    AGENT_ASSIGNMENT_DPD1_DPD30 = "agent_assignment_dpd1_dpd30"
    AGENT_ASSIGNMENT_DPD31_DPD60 = "agent_assignment_dpd31_dpd60"
    AGENT_ASSIGNMENT_DPD61_DPD90 = "agent_assignment_dpd61_dpd90"
    AGENT_ASSIGNMENT_DPD91PLUS = "agent_assignment_dpd91plus"
    AGENT_ASSIGNMENT_DPD1_DPD29 = "agent_assignment_dpd1_dpd29"
    AGENT_ASSIGNMENT_DPD30_DPD59 = "agent_assignment_dpd30_dpd59"
    AGENT_ASSIGNMENT_DPD60_DPD89 = "agent_assignment_dpd60_dpd89"
    AGENT_ASSIGNMENT_DPD90PLUS = "agent_assignment_dpd90plus"
    AGENT_ASSIGNMENT_DPD1_DPD15 = "agent_assignment_dpd1_dpd15"
    AGENT_ASSIGNMENT_DPD16_DPD29 = "agent_assignment_dpd16_dpd29"
    AGENT_ASSIGNMENT_DPD30_DPD44 = "agent_assignment_dpd30_dpd44"
    AGENT_ASSIGNMENT_DPD45_DPD59 = "agent_assignment_dpd45_dpd59"

    BYPASS_FAST_TRACK_122 = "bypass_fast_track_122"
    AUTO_CALL_PING_122 = "auto_call_ping_122"
    AUTO_CALL_PING_138 = "auto_call_ping_138"
    AUTODIALER_SESSION_DELAY = 'autodialer_session_delay'
    ROBOCALL_SET_CALLED = 'robocall_set_called'
    PREDICTIVE_MISSED_CALL = "predictive_missed_call"
    DISBURSEMENT_TRAFFIC = 'disbursement_traffic'
    BLACKLIST_CHECK = "advance_ai_blacklist_check"
    ID_CHECK = "advance_ai_id_check"
    APPLICATION_AUTO_EXPIRATION = "application_auto_expiration"
    V20B_SCORE = "v20b_score"
    ISO_COLLECTION = 'iso_collection'
    INSTANT_EXPIRATION_WEB_APPLICATION = 'instant_expiration_web_application'
    MONTY_SMS = 'monty_sms_as_primary'
    PENDING_DISBURSEMENT_NOTIFICATION_MEMBER = 'pending_disbursement_notification_member'
    DISBURSEMENT_AUTO_RETRY = 'disbursement_auto_retry'
    FTM_CONFIGURATION = 'ftm_configuration'
    NOTIFICATION_BALANCE_AMOUNT = 'notification_balance_amount'
    BCA_DISBURSEMENT_AUTO_RETRY = 'bca_disbursement_auto_retry'
    SMS_ACTIVATION_PAYLATER = 'sms_activation_paylater'
    LLA_TEMPLATE = 'lender_loan_agreement_template'
    DISBURSEMENT_TRAFFIC_MANAGE = 'disbursement_traffic_manage'
    REPAYMENT_TRAFFIC_SETTING = 'repayment_traffic_management'
    SUSPEND_ACCOUNT_PAYLATER = 'terminated_account_paylater'
    MANUAL_CASHBACK_PROMO = 'manual_cashback_promo'
    BCA_PENDING_STATUS_CHECK_IN_170 = 'bca_pending_status_check_in_170'
    XFERS_WITHDRAWAL = 'xfers_withdrawal'
    FORCE_HIGH_SCORE = 'force_high_creditscore'
    AUTO_APPROVAL_GLOBAL_SETTING = 'auto_approval_global_setting'
    DEFAULT_LENDER_MATCHMAKING = 'default_lender_matchmaking'
    MINTOS_INTEREST_RATE = 'mintos_interest_rate'
    AXIATA_MULTIPLE_LOAN = 'axiata_mutiple_loan'
    FACE_RECOGNITION = 'face_recognition'
    SLACK_NOTIFICATION_FACE_RECOGNITION = 'slack_notification_face_recognition'
    EXPIRED_147_FACE_RECOGNITION = 'expired_147_face_recognition'
    FRAUD_MODEL_EXPERIMENT = 'fraud_model_experiment'
    HIGH_SCORE_FULL_BYPASS = 'high_score_full_bypass'
    SONIC_BYPASS = 'sonic_bypass'
    SPECIAL_EVENT_BINARY = 'special_event_binary'
    AFFORDABILITY_VALUE_DISCOUNT = 'affordability_value_discount'
    FDC_INQUIRY_CHECK = 'fdc_inquiry_check'
    RETRY_FDC_INQUIRY = 'retry_fdc_inquiry'
    SCHEDULED_RETRY_FDC_INQUIRY = 'scheduled_retry_fdc_inquiry'
    LOAN_REFINANCING = 'loan_refinancing'
    COVID_REFINANCING = 'covid_refinancing'
    DELAY_C_SCORING = 'delay_scoring_and_notifications_for_C'
    WARNING_LETTER_CONTACTS = 'warning_letter_contacts'
    COLLECTION_OFFER_GENERAL_WEBSITE = 'collection_offer_general_website'
    SENT_EMAIl_AND_TRACKING = 'sent_email_and_tracking'
    MOENGAGE_EVENT = 'moengage_event'
    OCR_SETTING = 'ocr_setting'
    ACCOUNTING_CUT_OFF_DATE = 'accounting_cut_off_date'
    PIN_SETTING = 'pin_setting'
    ACTIVE_JULO1_FLAG = 'active_julo1_flag'
    ACCOUNT_REACTIVATION_SETTING = 'account_reactivation_setting'
    DIGITAL_SIGNATURE_THRESHOLD = 'digital_signature_threshold'
    VOICE_RECORDING_THRESHOLD = 'voice_recording_threshold'
    PRIVY_REUPLOAD_SETTINGS = 'privy_reupload_settings'
    CREDIT_LIMIT_REJECT_AFFORDABILITY = 'credit_limit_reject_affordability_value'
    AXIATA_DISTRIBUTOR_GRACE_PERIOD = 'axiata_distributor_grace_period'
    RISKY_LOAN_PURPOSE = 'risky_loan_purpose'
    XFERS_MANUAL_DISBURSEMENT = 'xfers_manual_disbursement'
    LOAN_MAX_ALLOWED_DURATION = 'loan_max_allowed_duration'
    EVER_ENTERED_B5_J1_EXPIRED_CONFIGURATION = 'ever_entered_b5_j1_expired_configuration'
    NOTIFICATION_MINIMUM_PARTNER_DEPOSIT_BALANCE = 'notification_minimum_partner_deposit_balance'
    CLCS_SCRAPED_SCHEDULE = 'clcs_scraped_schedule'
    CASHBACK_DELAY_LIMIT = 'cashback_delay_limit_threshold'
    EXPIRY_TOKEN_SETTING = 'expiry_token_setting'
    GRAB_STOP_REGISTRATION = 'grabmodal_stop_registration'
    WEB_MODEL_FDC_RETRY_SETTING = 'web_model_fdc_retry_setting'
    CASHBACK_EXPIRED_CONFIGURATION = 'cashback_expired_configuration'
    MINIMUM_AMOUNT_TRANSACTION_LIMIT = 'minimum_amount_transaction_limit'
    FRAUD_MISMATCH_NAME_IN_BANK_THRESHOLD = 'fraud_mismatch_name_in_bank_threshold'
    CACHE_BULK_DOWNLOAD_EXPIRED_SETTING = 'cache_bulk_download_expired_setting'
    COOTEK_LATE_DPD_SETTING = 'cootek_late_dpd_setting'
    DISBURSEMENT_STEP_1_NON_CASH = 'disbursement_step_1_non_cash'
    AUTODIALER_LOGIC = 'autodialer_logic'
    LIVENESS_DETECTION = 'liveness_detection'
    BONZA_LOAN_SCORING = 'bonza_loan_scoring'
    CAMPAIGN_190_SETTINGS = "campaign_190_settings"
    IN_APP_PTP_SETTING = 'in_app_ptp_setting'
    SENDING_RECORDING_CONFIGURATION = 'sending_recording_configuration'
    SLACK_NOTIFICATION_NEGATIVE_WORDS_THRESHOLD = 'slack_notification_negative_words_threshold'
    IN_APP_CALLBACK_SETTING = 'in_app_callback_setting'
    QRIS_MERCHANT_BLACKLIST = "qris_merchant_blacklist"
    BSS_CHANNELING = "bss_channeling"
    BSS_CHANNELING_WHITELIST = "bss_channeling_whitelist"
    BSS_CHANNELING_RETRY = "bss_channeling_retry"
    QRIS_MERCHANT_BLACKLIST_NEW = 'qris_blacklist_merchant_new'
    MAGIC_LINK_EXPIRY_TIME = "magic_link_expiry_time"
    PARTNER_PIN_EXPIRY_TIME = "partner_pin_expiry_time"
    FDC_MERCHANT_BINARY_CHECK = "fdc_merchant_binary_check"
    PARTNER_ELIGIBLE_USE_RENTEE = "partner_eligible_use_rentee"
    B4_EXPIRED_THRESHOLD = 'b4_expired_threshold'
    CFS = 'cfs'
    J_SCORE_HISTORY_CONFIG = 'j_score_history_config'
    SALES_OPS = 'sales_ops'
    SALES_OPS_REVAMP = 'sales_ops_revamp'
    DAILY_DISBURSEMENT_LIMIT = 'daily_disbursement_limit'
    SPECIAL_COHORT_SPECIFIC_LOAN_DISBURSED_DATE = 'special_cohort_specific_loan_disbursed_date'
    PARTNER_ELIGIBLE_USE_J1 = "partner_eligible_use_j1"
    PASS_BINARY_AND_DECISION_CHECK = 'pass binary & decision check'
    SEND_EMAIL_EFISHERY_ACCOUNT_PAYMENTS_REPORT = 'send_email_efishery_account_payments_report'
    LIVENESS_DETECTION_ANDROID_LICENSE = 'liveness_detection_android_license'
    DIALER_PARTNER_DISTRIBUTION_SYSTEM = 'dialer_partner_distribution_system'
    TUTORIAL_AUTODEBET = 'tutorial_autodebet'
    GRAB_PUSH_NOTIFICATION = 'grab_push_notification_setting'
    LOAN_DURATION_DEFAULT_INDEX = 'loan_duration_default_index'
    LEAD_GEN_PARTNER_CREDIT_SCORE_GENERATION = 'lead_gen_partner_credit_score_generation'
    EMULATOR_DETECTION = 'emulator_detection'
    RECIPIENTS_EMAIL_EFISHERY_DISBURSE_BULK = 'recipients_email_efishery_disburse_bulk'
    RECIPIENTS_EMAIL_DAGANGAN_DISBURSE_BULK = 'recipients_email_dagangan_disburse_bulk'
    LOCK_EMAIL_SMS_BUTTON_SETTING = 'lock_email_sms_button_setting'
    FDC_TIMEOUT = 'fdc_timeout'
    BYPASS_LENDER_MATCHMAKING_PROCESS = 'bypass_lender_matchmaking_process'
    BYPASS_LENDER_MATCHMAKING_PROCESS_BY_PRODUCT_LINE = (
        'bypass_lender_matchmaking_process_by_product_line'
    )
    CREDIT_CARD = 'credit_card'
    REFINANCING_RESTRICT_CHANNELING_LOAN = 'refinancing_restrict_channeling_loan'
    PARTNERSHIP_BULK_DISBURSEMENT_DELAY = "partnership_bulk_disbursement_delay"
    ADJUSTMENT_ACCOUNT_DISTRIBUTION = 'adjustment_account_distribution'
    EMAIL_BUKUWARUNG_DISBURSE_BULK = 'email_bukuwarung_disburse_bulk'
    CASHBACK = 'cashback'
    RECIPIENTS_EMAIL_EFISHERY_190_APPLICATION = 'recipients_email_efishery_190_application'
    RECIPIENTS_EMAIL_DAGANGAN_190_APPLICATION = 'recipients_email_dagangan_190_application'
    BSS_CHANNELING_CUTOFF = 'bss_channeling_cutoff'
    ECOMMERCE_EXPERIMENT = 'ecommerce_experiment'
    XENDIT_STEP_ONE_DISBURSEMENT = 'xendit_step_1_disbursement'
    EMAIL_OTP = 'email_otp'
    EF_PRE_APPROVAL = 'employee_financing_pre_approval'
    CREDIT_LIMIT_ROUNDING_DOWN_VALUE = 'credit_limit_rounding_down_value'
    NOTIFICATION_MINIMUM_XENDIT_BALANCE = 'notification_minimum_xendit_balance'
    GRAB_DEDUCTION_SCHEDULE = 'grab_deduction_schedule'
    XENDIT_WHITELIST = 'xendit_whitelist'
    AUTODEBET_CUSTOMER_EXCLUDE_FROM_INTELIX_CALL = 'autodebet_customer_exclude_from_intelix_call'
    CHECKOUT_EXPERIENCE = 'checkout_experience'
    USE_NEW_SEPULSA_BASE_URL = 'use_new_sepulsa_base_url'
    PAYLATER_PARTNER_TEMPORARY_BLOCK_PERIOD = "paylater_partner_temporary_block_period"
    MOBILE_PHONE_1_OTP = 'mobile_phone_1_otp'
    FDC_RISKY_CHECK = 'fdc_risky_check'
    PARTNERSHIP_COUNTDOWN_NOTIFY_105_APPLICATION = "partnership_countdown_notify_105_application"

    EXPIRE_CASHBACK_DATE_SETTING = 'expire_cashback_date_setting'
    CASHBACK_DPD_PAY_OFF = 'cashback_dpd_pay_off'
    RETRY_MECHANISM_AND_SEND_ALERT_FOR_UNSENT_INTELIX_ISSUE = \
        'retry_mechanism_and_send_alert_for_unsent_intelix_issue'
    GRAB_INTELIX_CALL = 'grab_intelix_call'
    JULO_STARTER = 'julo_starter'
    SPHINX_THRESHOLD = 'sphinx_threshold'
    GRAB_WRITE_OFF = 'grab_write_off'
    FRAUD_ATO_DEVICE_CHANGE = 'fraud_ato_device_change'
    PUSDAFIL = 'pusdafil'
    JULOSHOP_WHITELIST = 'juloshop_whitelist'
    DANA_LATE_FEE = 'dana_late_fee'
    MANDIRI_PAYMENT_METHOD_HIDE = 'mandiri_payment_method_hide'
    GOPAY_ONBOARDING_PAGE = 'gopay_onboarding_page'
    GRAB_REFERRAL_PROGRAM = 'grab_referral_program'
    GOPAY_ACTIVATION_LINKING = 'gopay_activation_linking'
    WHITELIST_GOPAY = 'whitelist_gopay'
    SEON_FRAUD_SCORE = 'seon_fraud_score'
    PHONE_NUMBER_DELETE = "phone_number_delete_email_setup"
    GRAB_DEFENCE_FRAUD_SCORE = 'grab_defence_fraud_score'
    OJK_AUDIT_FEATURE = 'ojk_audit_feature'
    CRM_HIDE_MENU = 'crm_hide_menu'
    GRAB_C_SCORE_FEATURE_FOR_INTELIX = 'grab_c_score_feature_for_intelix'
    FRAUD_VELOCITY_MODEL_GEOHASH = 'fraud_velocity_model_geohash'
    AUTODEBET_BENEFIT_CONTROL = 'autodebet_benefit_control'
    LIST_LENDER_INFO = 'list_lender_info'
    DANA_LENDER_AUTO_APPROVE = 'dana_lender_auto_approve'
    WHITELIST_MANUAL_APPROVAL = 'whitelist_manual_approval'
    HIDE_PARTNER_LOAN = 'hide_partner_loan'
    GRAB_FILE_TRANSFER_CALL = 'grab_file_transfer_call'
    SIGNATURE_KEY_CONFIGURATION = 'signature_key_configuration'
    ORDER_PAYMENT_METHODS_BY_GROUPS = 'order_payment_methods_by_groups'
    MONNAI_FRAUD_SCORE = 'monnai_fraud_score'
    DANA_MASSIVE_LOG = 'dana_massive_log'
    DANA_AGREEMENT_PASSWORD = 'dana_agreement_password'
    NEXMO_NUMBER_RANDOMIZER = 'nexmo_number_randomizer'
    DANA_WHITELIST_USERS = 'dana_whitelist_users'
    BINARY_CHECK_MOCK = 'binary_check_mock'
    APP_RISKY_CHECK_MOCK = 'app_risky_check_mock'
    EMULATOR_DETECTION_MOCK = 'emulator_detection_mock'
    HEIMDALL_MOCK_RESPONSE_SET = 'heimdall_mock_response_set'
    BPJS_MOCK_RESPONSE_SET = 'bpjs_mock_response_set'
    FDC_MOCK_RESPONSE_SET = 'fdc_mock_response_set'
    DUKCAPIL_MOCK_RESPONSE_SET = 'dukcapil_mock_response_set'
    CONFIG_FLOW_LIMIT_JSTARTER = 'config_flow_to_limit_jstarter'
    SECOND_CHECK_JSTARTER_MESSAGE = 'second_check_notif_jstarter'
    BLOCK_BNI_VA_AUTO_GENERATION = 'block_bni_va_auto_generation'
    SESSION_LIMIT_FOR_INFOCARD = 'session_limit_for_infocard'
    DUKCAPIL_MOCK_RESPONSE_SET = 'dukcapil_mock_response_set'
    DUKCAPIL_CALLBACK_MOCK_RESPONSE_SET = 'dukcapil_callback_mock_response_set'
    DISABLE_PAYMENT_METHOD = 'disable_payment_method'
    CREDIT_MATRIX_REPEAT_SETTING = 'credit_matrix_repeat_setting'
    SHOPEE_SCORING = "shopee_scoring"
    TRIGGER_RESCRAPE_AND_FORCE_LOGOUT = 'trigger_rescrape_and_force_logout'
    AUTO_RETROFIX = 'auto_retrofix'
    MARK_120_EXPIRED_IN_1_DAYS = 'mark_120_expired_in_1_days'
    MYCROFT_SCORE_CHECK = 'mycroft_score_check'
    ACTIVATION_CALL_BYPASS = 'activation_call_bypass'
    LOAN_STATUS_PATH_CHECK = 'loan_status_path_check'
    DANA_ENABLE_REPAYMENT_ASYNCHRONOUS = 'dana_enable_repayment_async'
    DANA_ENABLE_PAYMENT_ASYNCHRONOUS = 'dana_enable_payment_async'
    LOAN_PHONE_ROTATION_ROBOCALL = 'loan_phone_rotation_robocall'
    TUTORIAL_BOTTOM_SHEET = 'tutorial_bottom_sheet'
    REFINANCING_MAX_CAP_RULE_TRIGGER = 'refinancing_max_cap_rule_trigger'
    SPECIFIC_USER_FOR_JSTARTER = 'specific_user_for_jstarter'
    MYCROFT_THRESHOLD_SETTING = 'mycroft_threshold_setting'
    VALIDATE_LOAN_DURATION_WITH_SEPULSA_PAYMENT_POINT = \
        'validate_loan_duration_with_sepulsa_payment_point'
    LOAN_TAGGING_CONFIG = 'loan_tagging_config'
    SMILE_LIVENESS_DETECTION = 'smile_liveness_detection'
    GRAB_ROBOCALL_SETTING = 'grab_robocall_settings'
    SPHINX_NO_BPJS_THRESHOLD = 'sphinx_no_bpjs_threshold'
    AUTODEBET_GOPAY = 'autodebet_gopay'
    JTURBO_BYPASS = 'jturbo_bypass'
    GOPAY_BALANCE_ALERT = 'gopay_balance_alert'
    FRAUD_HOTSPOT = 'fraud_hotspot'
    SALES_OPS_BUCKET_LOGIC = 'sales_ops_bucket_logic'
    SAVING_INFORMATION_CONFIGURATION = 'saving_information_configuration'
    SAVING_INFORMATION_PAGE = 'saving_information_page'
    RECIPIENTS_BACKUP_PASSWORD = 'recipients_backup_password'
    IDFY_CONFIG_ID = 'idfy_config_id'
    IDFY_INSTRUCTION_PAGE = 'idfy_instruction_page'
    PAYMENT_METHOD_FAQ_URL = 'payment_method_faq_url'
    EMAIL_PAYMENT_REMINDER_SENDGRID_BOUNCE_TAKEOUT = \
        'email_payment_reminder_sendgrid_bounce_takeout'
    CHANNELING_PRIORITY = "channeling_priority"
    BJB_CHANNELING = "bjb_channeling"
    BJB_CHANNELING_WHITELIST = "bjb_channeling_whitelist"
    BJB_CHANNELING_RISK_ACCEPTANCE_CRITERIA = "bjb_channeling_risk_acceptance_criteria"
    CACHE_XFERS_USER_API_TOKEN = 'cache_xfers_user_api_token'
    FRAUD_BLACKLISTED_COMPANY = 'fraud_blacklisted_company'
    HIGH_RISK_ASN_TOWER_CHECK = 'high_risk_asn_tower_check'
    BLACKLISTED_ASN = 'blacklisted_asn'
    SHOPEE_WHITELIST_SCORING = 'shopee_whitelist_scoring'
    FRAUDSTER_FACE_MATCH = 'fraudster_face_match'
    MARKETING_LOAN_PRIZE_CHANCE = 'marketing_loan_prize_chance'
    ZERO_INTEREST_HIGHER_PROVISION = 'zero_interest_higher_provision'
    GRAB_PAYMENT_GATEWAY_RATIO = 'grab_payment_gateway_ratio'
    GRAB_AYOCONNECT_XFERS_FAILOVER = 'grab_ayoconnect_xfers_failover'
    PARTNERSHIP_FDC_MOCK_RESPONSE_SET = 'partnership_fdc_mock_response_set'
    SCHEDULER_DELETE_OLD_CUSTOMERS = 'scheduler_delete_old_customers'
    SELFIE_GEOHASH_CRM_IMAGE_LIMIT = 'selfie_geohash_crm_image_limit'
    LOAN_SMS_AFTER_ROBOCALL = 'loan_sms_after_robocall'
    DPD_WARNING_COLOR_TRESHOLD = 'dpd_warning_color_treshold'
    SIMILAR_AND_FRAUD_FACE_TIME_LIMIT = 'similar_and_fraud_face_time_limit'
    CUSTOMER_DATA_CHANGE_REQUEST = "customer_data_change_request"
    DANA_FDC_RESULT_RETRY_CONFIGURATION = 'dana_fdc_result_retry_configuration'
    DANA_PROVINCE_AND_CITY = 'dana_province_and_city'
    DANA_JOB = 'dana_job'
    GRAB_SMALLER_LOAN_OPTION = 'grab_smaller_loan_option'
    DISBURSEMENT_METHOD = 'disbursement_method'
    FRAUD_BLACKLISTED_POSTAL_CODE = 'fraud_blacklisted_postal_code'
    JULO_CARE_CONFIGURATION = 'julo_care_configuration'
    DANA_BLOCK_LOAN_STUCK_211_PAYMENT_CONSULT_TRAFFIC = (
        'dana_block_loan_stuck_211_payment_consult_traffic'
    )
    DANA_BLOCK_AUTO_RECOVER_MANUAL_UPLOAD = (
        'dana_block_auto_recover_manual_upload'
    )
    POWERCRED_FRAUD_CRITERIA = 'powercred_fraud_criteria'
    MF_LENDER_AUTO_APPROVE = 'merchant_financing_lender_auto_approve'
    AUTODEBET_DEDUCTION_DAY = 'autodebet_deduction_day'
    DANA_LINKING = 'dana_linking'
    DANA_LINKING_WHITELIST = 'dana_linking_whitelist'
    DANA_LINKING_ONBOARDING = 'dana_linking_onboarding'
    ONEKLIK_BCA = 'oneklik_bca'
    ONEKLIK_BCA_WHITELIST = 'oneklik_bca_whitelist'
    UNDERWRITING_NONFDC_AUTODEBET = 'underwriting_nonfdc_autodebet'
    AUTODEBET_ACTIVATION_PN_CONFIG = 'autodebet_activation_pn_config'
    JULO_CORE_EXPIRY_MARKS = 'julo_core_expiry_marks'
    TRUST_GUARD_SCORING = 'trust_guard_scoring'
    GRAB_C_SCORE_FEATURE_FOR_AI_RUDDER = 'grab_c_score_feature_for_ai_rudder'
    GRAB_AI_RUDDER_CALL = 'grab_ai_rudder_call'
    DANA_OTHER_PAGE_URL = 'dana_other_page_url'
    ALERT_FOR_STUCK_LOAN = 'alert_for_stuck_loan'
    FDC_PRE_CHECK_AGENT_ASSISTED = 'fdc_pre_check_agent_assisted'
    AGENT_ASSISTED_LIMIT_UPLOADER = 'agent_assited_limit_uploader'
    REVIVE_SEMI_GOOD_CUSTOMER = 'revive_semi_good_customer'
    FRAUD_BLACKLISTED_GEOHASH5 = 'fraud_blacklisted_geohash5'
    LDDE_V2_SETTING = 'ldde_v2_setting'
    GRAB_MANUAL_UPLOAD_FEATURE_FOR_AI_RUDDER = 'grab_manual_upload_feature_for_ai_rudder'
    IDFY_VIDEO_CALL_HOURS = 'idfy_video_call_hours'
    WAIVER_APPROVAL_REASON = 'waiver_approval_reason'
    LOAN_SELL_OFF_CONTENT_API = 'loan_sell_off_content_api'
    RISKY_CHANGE_PHONE_ACTIVITY_CHECK = 'risky_change_phone_activity_check'
    DBR_RATIO_CONFIG = 'dbr_ratio_config'
    LOAN_TAX_CONFIG = 'loan_tax_config'
    MOCK_GOOGLE_AUTH_API = 'mock_google_auth_api'
    CHECK_OTHER_ACTIVE_PLATFORMS_USING_FDC = 'check_other_active_platforms_using_fdc'
    PAYMENT_GATEWAY_ALERT = 'payment_gateway_alert'
    ONBOARDING_PII_VAULT_TOKENIZATION = 'onboarding_pii_vault_tokenization'
    GRAB_AI_RUDDER_DELETE_PHONE_NUMBER = 'grab_ai_rudder_delete_phone_number'
    CHECK_GTL = 'check_gtl'
    IPA_BANNER_V2 = 'ipa_banner_v2'
    LATE_FEE_RULE = 'late_fee_rule'
    DANA_CASH_LOAN = 'dana_cash_loan'
    LIMIT_CAP_EMERGENCY_CONTACT = 'limit_cap_emergency_contact'
    DANA_CASH_LOAN_REGISTRATION_USER_CONFIG  = 'dana_cash_loan_registration_user_config'
    DANA_SEOJK_RULE = "dana_seojk_rule"
    TECH_DRAGON_BALL = 'dragon_ball_project'
    BCA_INQUIRY_SNAP = 'bca_inqury_snap'
    PARTNERSHIP_CONFIG_PII_VAULT_TOKENIZATION = 'partnership_config_pii_vault_tokenization'
    JULO_FRESH_CONFIG = 'julo_fresh_config'
    FIELD_TRACKER_LOG = 'field_tracker_log'
    SWIFT_LIMIT_DRAINER = 'swift_limit_drainer'
    FRAUD_APPEAL_TEMPORARY_BLOCK = 'fraud_appeal_temporary_block'
    HOLDOUT_USERS_FROM_BSS_CHANNELING = 'holdout_users_from_bss_channeling'
    KTP_OCR_THRESHOLD_VALUE = 'ktp_ocr_threshold_value'
    NEW_OPENCV_KTP = 'new_opencv_ktp'
    GTL_CROSS_PLATFORM = 'gtl_cross_platform'
    APP_MINIMUM_REGISTER_VERSION = 'app_minimum_register_version'
    FACE_MATCHING_CHECK = 'face_matching_check'
    GRAB_DISBURSEMENT_RETRY = 'grab_disbursement_retry'
    PARTNERSHIP_IDEMPOTENCY_CHECK = 'partnership_idempotency_check'
    BPJS_RISKY_BYPASS = 'bpjs_risky_bypass'
    FASPAY_PROHIBIT_VA_PAYMENT = 'faspay_prohibit_va_payment'
    PARTNER_ACCOUNTS_FORCE_LOGOUT = 'partner_accounts_force_logout'
    TECH_INITIAL_RETROLOAD_DRAGON_BALL = 'initial_retroload_dragon_ball_project'
    COMMS_PRICE_CONFIG = 'comms_price_config'
    DANA_COLLECTION_TRACKING_PROCESS = 'dana_collection_tracking_process'
    DANA_COLLECTION_ON_OFF_REFACTOR_FUNCTION = 'dana_collection_on_off_refactor_function'
    BPJS_SUPER_BYPASS = 'bpjs_super_bypass'
    EMERGENCY_CONTACT_BLACKLIST = 'emergency_contact_blacklist'
    GRAB_3_MAX_CREDITORS_CHECK = "grab_3_max_creditors_check"
    AUTODEBET_IDFY_ENTRY_POINT = 'autodebet_idfy_entry_point'
    FAILED_BANK_NAME_VALIDATION_DURING_UNDERWRITING = (
        'failed_bank_name_validation_during_underwriting'
    )
    SHOW_DIFFERENT_PRICING_ON_UI = 'show_different_pricing_on_ui'
    EXCLUDE_LATEST_PAYMENT_METHOD = 'exclude_latest_payment_method'
    REPAYMENT_PROHIBIT_VA_PAYMENT = 'repayment_prohibit_va_payment'
    DANA_MONTHLY_INCOME = 'dana_monthly_income'
    GRAB_ADMIN_FEE_TIERING = 'Grab_admin_fee_tiering'
    OTP_SWITCH = 'otp_switch'
    SALES_OPS_ALERT = 'sales_ops_alert'
    ONBOARDING_PII_VAULT_DETOKENIZATION = 'onboarding_pii_vault_detokenization'
    AUTODEBET_IDFY_PN_TIMER = 'autodebet_idfy_notification_timer'
    AUTODEBIT_IDFY_INSTRUCTION_PAGE = 'autodebit_idfy_instruction_page'
    AUTODEBET_IDFY_CONFIG_ID = 'autodebet_idfy_config_id'
    PRODUCT_LOCK_IN_APP_BOTTOM_SHEET = 'product_lock_in_app_bottom_sheet'
    SUSPEND_CHANGE_REASON_MAP_PRODUCT_LOCK_CODE = 'suspend_change_reason_map_product_lock_code'
    JUICY_SCORE_FRAUD_SCORE = 'juicy_score_fraud_score'
    TELCO_SCORE = 'telco_score'
    SWAPOUT_CHECK_HOLDOUT = 'swapout_check_holdout'
    PROMO_CODE_FOR_CASHBACK_INJECTION = 'promo_code_for_cashback_injection'
    MONNAI_INSIGHT_INTEGRATION = 'monnai_insight_integration'
    GOLDFISH_BYPASS = "goldfish_bypass"
    CREDGENICS_INTEGRATION = 'credgenics_integration'
    CREDGENICS_REPAYMENT = 'credgenics_repayment'
    HIGH_RISK = "high_risk"
    FRAUD_FACE_STORING = 'fraud_face_storing'
    PRODUCT_PICKER_BYPASS_LOGIN_CONFIG = 'product_picker_bypass_login_config'
    GRAB_EMERGENCY_CONTACT = "grab_emergency_contact_consent_flow"
    AUTODEBIT_IDFY_INSTRUCTION_PAGE = 'autodebit_idfy_instruction_page'
    J_FINANCING_TOKEN_CONFIG = 'j_financing_token_config'
    ANTIFRAUD_BINARY_CHECK = 'antifraud_binary_check'
    GD_DEVICE_SHARING = "gd_device_sharing"
    FACE_SIMILARITY_THRESHOLD_JTURBO = 'face_similarity_threshold_jturbo'
    NUMBER_TENURE_OPTION = 'number_tenure_option'
    LOAN_WRITE_OFF = 'loan_write_off'
    OMNICHANNEL_INTEGRATION = 'omnichannel_integration'
    PUSDAFIL_LENDER_REPAYMENT_GDRIVE_PROCESS = "pusdafil_lender_repayment_gdrive_process"
    PARTNERSHIP_MAX_PLATFORM_CHECK_USING_FDC = 'partnership_max_platform_check_using_fdc'
    TELCO_MAID_LOCATION_FEATURE = 'telco_maid_location_feature'
    LOAN_AMOUNT_DEFAULT_CONFIG = 'loan_amount_default_config'
    GD_DEVICE_SHARING = "gd_device_sharing"
    ANTIFRAUD_GRAB_DEFENCE = 'antifraud_grab_defence'
    ABC_BANK_NAME_VELOCITY = 'abc_bank_name_velocity'
    ANTIFRAUD_PII_VAULT_TOKENIZATION = "antifraud_pii_vault_tokenization"
    ANTIFRAUD_PII_VAULT_DETOKENIZATION = "antifraud_pii_vault_detokenization"
    CREDIT_DECISION_ENGINE_CDE = 'credit_decision_engine_cde'
    WAITING_LIST = 'waiting_list'
    MYCROFT_TURBO_THRESHOLD = 'mycroft_turbo_threshold'
    ANTIFRAUD_RATE_LIMIT = 'antifraud_rate_limit'
    WHITELIST_VA_BILL_AMOUNT_BCA = 'whitelist_va_bill_amount_bca'
    MOENGAGE_EWALLET_BALANCE = 'moengage_ewallet_balance'
    FRAUD_BLOCK_ACCOUNT_FEATURE = 'fraud_block_account'
    DELAY_DISBURSEMENT = 'delay_disbursement'
    FACE_MATCHING_SIMILARITY_THRESHOLD_JTURBO = 'face_matching_similarity_threshold_jturbo'
    QRIS_WHITELIST_ELIGIBLE_USER = 'qris_whitelist_eligible_user'
    DIGISIGN = 'digisign'
    WHITELIST_DIGISIGN = 'whitelist_digisign'
    CLIK_MODEL = 'clik_model'
    ANTIFRAUD_API_ONBOARDING = 'antifraud_api_onboarding'
    GENERATE_XID_MAX_COUNT = 'generate_xid_max_count'
    SIMILARITY_CHECK_APPLICATION_DATA = 'similarity_check_application_data'
    NEW_LIVENESS_DETECTION = 'new_liveness_detection'
    COMMS_PRICE_CONFIG = 'comms_price_config'
    USER_SEGMENT_CHUNK_SIZE = 'user_segment_chunk_size'
    USER_SEGMENT_CHUNK_INTEGRITY_CHECK_TTL = 'user_segment_chunk_integrity_check_ttl'
    SMS_CAMPAIGN_FAILED_PROCESS_CHECK_TTL = 'sms_campaign_failed_process_check_ttl'
    OVO_TOKENIZATION = 'ovo_tokenization'
    OVO_TOKENIZATION_WHITELIST = 'ovo_tokenization_whitelist'
    OVO_TOKENIZATION_ONBOARDING = 'ovo_tokenization_onboarding'
    AUTODEBET_IDFY_CALL_BUTTON = 'autodebet_idfy_call_button'
    THOR_TENOR_INTERVENTION = 'thor_tenor_intervention'
    FDC_UPLOAD_FILE_SIK = 'fdc_upload_file_sik'
    ABC_TRUST_GUARD = 'abc_trust_guard'
    EMAIL_SERVICE_INTEGRATION = 'email_service_integration'
    EXTERNAL_WARNING_LETTER = 'external_warning_letter'
    HIDE_PAYMENT_METHODS_BY_LENDER = 'hide_payment_methods_by_lender'
    SKIPTRACE_STATS_SCHEDULER = 'skiptrace_stats_scheduler'
    LOGIN_ERROR_MESSAGE = 'login_error_message'
    LIVENESS_DETECTION_IOS_LICENSE = 'liveness_detection_ios_license'
    LIMIT_ADJUSTMENT_FACTOR = 'limit_adjustment_factor'
    OVO_TOKENIZATION = 'ovo_tokenization'
    OVO_TOKENIZATION_WHITELIST = 'ovo_tokenization_whitelist'
    FDC_LENDER_MAP = 'fdc_lender_map'
    ELIGIBLE_ENTRY_LEVEL_SWAPIN = 'eligible_entry_level_swapin'
    VALIDATION_IMAGE_UPLOAD_STATUS = 'validation_image_upload_status'
    REPOPULATE_ZIPCODE = 'repopulate_zipcode'
    GENERATE_CREDIT_SCORE = 'generate_credit_score'
    LATE_FEE_GRACE_PERIOD = 'late_fee_grace_period'
    PARTNERSHIP_LEADGEN_CONFIG_CREDIT_MATRIX = 'partnership_leadgen_config_credit_matrix'
    ONBOARDING_BANK_VALIDATION_PG = 'onboarding_bank_validation_pg'
    CROSS_OS_LOGIN = 'cross_OS_login'
    CROSS_SELLING_CONFIG = 'cross_selling_config'
    EMAIL_PAYMENT_SUCCESS = 'email_payment_success'
    DAILY_DISBURSEMENT_LIMIT_WHITELIST = 'daily_disbursement_limit_whitelist'
    CASHBACK_DRAWER_ENCOURAGEMENT = 'cashback_drawer_encouragement'
    DUKCAPIL_FR_THRESHOLD_PARTNERSHIP_LEADGEN = 'dukcapil_fr_threshold_partnership_leadgen'
    REPAYMENT_PAYBACK_SERVICE_LIST = 'repayment_payback_service_list'
    INSTRUCTION_VERIFICATION_DOCS = 'instruction_verification_docs'
    QRIS_LANDING_PAGE_CONFIG = "qris_landing_page_config"
    PAYMENT_METHOD_SWITCH = 'payment_method_switch'
    ORION_FDC_LIMIT_GENERATION = 'orion_fdc_limit_generation'
    ABC_TRUST_GUARD_IOS = 'abc_trust_guard_ios'
    LENDER_ID_NOT_ELIGIBLE_FOR_PAYDATE_CHANGE = 'lender_id_not_eligible_for_paydate_change'
    IDFY_NFS_DEPENDENCY = 'idfy_nfs_dependency'
    ADDITIONAL_MESSAGE_SUBMIT_APP = 'additional_message_submit_app'
    HIT_FDC_FOR_REJECTED_CUSTOMERS = 'hit_fdc_for_rejected_customers'


class MobileFeatureNameConst(object):
    PRE_LONG_FORM_GUIDANCE_POP_UP = "pre_long_form_guidance_pop_up"
    ADDRESS_FRAUD_PREVENTION = "address_fraud_prevention"
    ECOMMERCE_MESSAGE = 'ecommerce_message'
    CASHBACK_FAQS = 'cashback_faqs'
    EMAIL_OTP = 'email_otp'
    GLOBAL_OTP = 'otp_setting'
    FRAUD_INFO = 'fraud_info'
    KEAMANAN_PAGE = 'keamanan_page'
    FRAUD_REPORT_FORM_BUTTON = 'fraud_report_form_button'
    TRANSACTION_METHOD_WHITELIST = 'transaction_method_whitelist'
    JSTARTER_EARLY_CHECKS = 'jstarter_early_checks'
    JSTARTER_REJECTION_PAGE_MESSAGE = 'jstarter_rejection_page_message'
    LUPA_PIN = 'lupa_pin'
    BOTTOMSHEET_CONTENT_PRODUCT_PICKER = 'bottomsheet_content_product_picker'
    GOPAY_FAQ_SETTING = 'gopay_faq_setting'
    GOPAY_AUTODEBET_CONSENT = 'gopay_autodebet_consent'
    MANDIRI_AUTODEBET_CONSENT = 'mandiri_autodebet_consent'
    RESET_PHONE_NUMBER = 'reset_phone_number'
    CLIK_INTEGRATION = 'clik_integration'
    TRANSACTION_RESULT_FE_MESSAGES = 'transaction_result_fe_messages'
    DANA_AUTODEBET_CONSENT = 'dana_autodebet_consent'
    WHATSAPP_DYNAMIC_ACTION_TYPE = 'whatsapp_dynamic_action_type'
    DYNAMIC_OTP_PAGE = 'dynamic_otp_page'
    TRANSACTION_METHOD_CAMPAIGN = 'transaction_method_campaign'
    AUTODEBET_REMINDER_SETTING = 'autodebet_reminder_setting'
    WHATSAPP_OTP_CHECK_EXCLUSION = 'whatsapp_otp_check_exclusion'
    CX_LIVE_CHAT_REGISTRATION_FORM = 'cx_live_chat_registration_form'
    CHANGE_PIN_INSTRUCTIONAL_BANNER = 'change_pin_instructional_banner'
    ONBOARDING_BANK_VALIDATION_PG = 'onboarding_bank_validation_pg'
    CASHBACK_CLAIM_FAQS = 'cashback_claim_faqs'
    BOTTOMSHEET_CONTENT_CASHBACK_CLAIM = 'bottomsheet_content_cashback_claim'


class BypassITIExperimentConst(object):
    """collection constants Experiments."""

    MIN_EXPENSE_AMOUNT = 1500000
    MIN_AFFORDABILITY_STL = 550000
    MIN_AFFORDABILITY_MTL = 580000
    MIN_AMOUNT_OFFER_MTL = 2000000
    MAX_RANGE_COMPARE_INSTALLMENT = 150000
    MAX_MONTHLY_INCOME = 18000000
    MAX_LOAN_DURATION_OFFER = 4
    REDUCE_INSTALLMENT_AMOUNT = 500000
    INTEREST_RATE_MONTHLY_MTL = 0.04
    INTEREST_RATE_MONTHLY_STL = 0.10
    RATE_DTI = 0.30
    RATE_TIER1_MAE = 0.0341572861
    RATE_TIER2_MAE = 0.0392141031
    RATE_TIER3_MAE = 0.0495727552
    RATE_TIER4_MAE = 0.0538076953
    RATE_TIER5_MAE = 0.058683144
    TIER1_MAE_WEIGHT = 1
    TIER2_MAE_WEIGHT = 1
    TIER3_MAE_WEIGHT = 2
    TIER4_MAE_WEIGHT = 3
    TIER5_MAE_WEIGHT = 4
    VERSION_CREDIT_SCORE_FAST_TRACK_122 = 3
    MIN_SCORE_TRESHOLD_MTL = 0.92
    MIN_SCORE_TRESHOLD_STL = 0.88
    CRITERIA_EXPERIMENT_GENERAL = ['1', '2', '3', '4', '5', '6', '7']
    CRITERIA_EXPERIMENT_ITI_123 = []
    CRITERIA_EXPERIMENT_ITI_172 = []
    CRITERIA_EXPERIMENT_FT_172 = ['1', '2', '3', '4', '5', '6', '7']
    CRITERIA_EXPERIMENT_ITIV5_THRESHOLD = 89
    # current active score type is 'A' so we don't need change the 'B' section
    MIN_CREDIT_SCORE_ITIV5 = {
        'A': 0.80,
        'B': 0.90,
    }
    MAX_ITI_MONTHLY_INCOME = 10000000


class AgentAssignmentTypeConst(object):
    DPD1_DPD29 = 'dpd1_dpd29'
    DPD30_DPD59 = 'dpd30_dpd59'
    DPD60_DPD89 = 'dpd60_dpd89'
    DPD90PLUS = 'dpd90plus'
    # split bucket
    DPD1_DPD15 = 'dpd1_dpd15'
    DPD16_DPD29 = 'dpd16_dpd29'
    DPD30_DPD44 = 'dpd30_dpd44'
    DPD45_DPD59 = 'dpd45_dpd59'

    # new collection bucket DPDB = Due Payment Date Before
    DPD1_DPD10 = 'dpd1_dpd10'
    DPD11_DPD40 = 'dpd11_dpd40'
    DPD41_DPD70 = 'dpd41_dpd70'
    DPD71_DPD90 = 'dpd71_dpd90'
    DPD91PLUS = 'dpd91plus'

    @classmethod
    def all(cls):
        return [
            cls.DPD1_DPD29,
            cls.DPD30_DPD59,
            cls.DPD60_DPD89,
            cls.DPD90PLUS,
            cls.DPD1_DPD15,
            cls.DPD16_DPD29,
            cls.DPD30_DPD44,
            cls.DPD45_DPD59,
        ]


class PayslipOptionalCondition(object):
    SCORE_THRESHOLD = 0.80


class CreditExperiments(object):
    RABMINUS165 = "RABMINUS165"  # exp to provide b- for previousley loan complied users
    CODES = [RABMINUS165]


class LoanVendorList(object):
    VENDOR_LIST = ['telmark', 'asiacollect', 'mbacollection', 'collmatra']


class ReminderTypeConst(object):
    SMS_TYPE_REMINDER = 'sms'
    EMAIL_TYPE_REMINDER = 'email'
    ROBOCALL_TYPE_REMINDER = 'robocall'


class VendorConst(object):
    NEXMO = 'nexmo'
    MONTY = 'monty'
    SENDGRID = 'sendgrid'
    INFOBIP = 'infobip'
    ALICLOUD = 'alicloud'
    WHATSAPP_SERVICE = 'whatsapp_service'


class AddressPostalCodeConst(object):
    WIB_POSTALCODE = list(
        list(range(23111, 24795))
        + list(range(20111, 23000))
        + list(range(25111, 27780))
        + list(range(28111, 29570))
        + list(range(29111, 29879))
        + list(range(36111, 37575))
        + list(range(30111, 32389))
        + list(range(34111, 35687))
        + list(range(33111, 33793))
        + list(range(38113, 39378))
        + list(range(10110, 14541))
        + list(range(16110, 17731))
        + list(range(40111, 46477))
        + list(range(15111, 15821))
        + list(range(42111, 42456))
        + list(range(50111, 54475))
        + list(range(56111, 59585))
        + list(range(55111, 55894))
        + list(range(60111, 69494))
        + list(range(78111, 79683))
        + list(range(73111, 74875))
    )

    WITA_POSTALCODE = list(
        list(range(77111, 77575))
        + list(range(75111, 77382))
        + list(range(70111, 72277))
        + list(range(80111, 82263))
        + list(range(83115, 84460))
        + list(range(85111, 87285))
        + list(range(91311, 91592))
        + list(range(94111, 94982))
        + list(range(90111, 91274))
        + list(range(91611, 92986))
        + list(range(93111, 93964))
        + list(range(95111, 96000))
        + list(range(96111, 96575))
    )

    WIT_POSTALCODE = list(
        list(range(97114, 97670))
        + list(range(97711, 97870))
        + list(range(98511, 99977))
        + list(range(98011, 98496))
    )
    PYTZ_TIME_ZONE_ID = {
        'WIB': 'Asia/Jakarta',
        'WITA': 'Asia/Makassar',
        'WIT': 'Asia/Jayapura',
    }
    '''
        we dont store WIB because we set default value WIB so postal code outside this list
        we treat it as WIB
    '''
    INDONESIAN_TIMEZONE = {
        'WITA': [
            range(77111, 77575),
            range(75111, 77382),
            range(70111, 72277),
            range(80111, 82263),
            range(83115, 84460),
            range(85111, 87285),
            range(91311, 91592),
            range(94111, 94982),
            range(90111, 91274),
            range(91611, 92986),
            range(93111, 93964),
            range(95111, 96000),
            range(96111, 96575),
        ],
        'WIT': [
            range(97114, 97670),
            range(97711, 97870),
            range(98511, 99977),
            range(98011, 98496),
        ],
    }


class ReferralConstant(object):
    CAMPAIGN_CODE = 'CICILBUNGA08'
    MIN_AMOUNT = 2000000


class WaiveCampaignConst(object):
    SELL_OFF_OCT = 'sell_off_oct'
    OSP_RECOVERY_APR_2020 = 'OSP_RECOVERY_APR_2020'
    RISKY_CUSTOMER_EARLY_PAYOFF = 'RISKY_CUSTOMER_EARLY_PAYOFF'


class ExperimentDate(object):
    WA_EXPERIMENT_START_DATE = '2019-10-22'
    WA_EXPERIMENT_END_DATE = '2019-11-04'


class LocalTimeType(object):
    WIB = 'wib'
    WITA = 'wita'
    WIT = 'wit'


class FaceRecognition(object):
    BAD_IMAGE_QUALITY = 'bad_image_quality'
    NO_FACE_FOUND = 'no_face_found'
    NO_FACE_AND_BAD_IMAGE_QUALITY = 'no_face_and_bad_image_quality'
    MAX_FACES = 1
    AWS = 'AWS'
    QUALITY_FILTER = {'HIGH': 'HIGH', 'AUTO': 'AUTO', 'LOW': 'LOW', 'MEDIUM': 'MEDIUM'}


class HighScoreFullByPassConstant(object):
    @classmethod
    def application_status(cls):
        return [
            ApplicationStatusCodes.APPLICANT_CALLS_SUCCESSFUL,
            ApplicationStatusCodes.APPLICATION_FLAGGED_FOR_SUPERVISOR,
            ApplicationStatusCodes.VERIFICATION_CALLS_ONGOING,
            ApplicationStatusCodes.CALL_ASSESSMENT,
            ApplicationStatusCodes.DOCUMENTS_VERIFIED,
            ApplicationStatusCodes.DOCUMENTS_VERIFIED_BY_THIRD_PARTY,
            ApplicationStatusCodes.VERIFICATION_CALLS_ONGOING_BY_THIRD_PARTY,
            ApplicationStatusCodes.DOCUMENTS_SUBMITTED,
            ApplicationStatusCodes.FACE_RECOGNITION_AFTER_RESUBMIT,
            ApplicationStatusCodes.APPLICATION_RESUBMISSION_REQUESTED,
        ]


class Affordability(object):
    AFFORDABILITY_TYPE = "130 Affordability"
    AFFORDABILITY_TYPE_1_TENURE = "130 Affordability - 1 tenure"
    AFFORDABILITY_TYPE_2_TENURE = "130 Affordability - 2 tenure"
    MONTHLY_INCOME_DTI = "Updated Monthly Income - DTI"
    MONTHLY_INCOME_NEW_AFFORDABILITY = "Updated Monthly Income - New affordability"
    REASON = {
        'sonic_preliminary': 'Sonic Preliminary check',
        'limit_generation': 'Limit Generation',
        'auto_update_affordability': \
            'auto update affordability after approve payslip/bank statement mission'
    }


class LoanGenerationChunkingConstant(object):
    AMOUNT_INCREMENT = 100000


class DigitalSignatureProviderConstant(object):
    DIGISIGN = 'digisign'
    PRIVY = 'privy'


class NexmoRobocallConst(object):
    TIME_OUT_DURATION = 3
    PROACTIVE_TIMEOUT_DURATION = 5
    ALL_PRODUCTS = ['nexmo_j1', 'j1', 'nexmo_grab', 'nexmo_dana', 'nexmo_turbo']
    WITHOUT_GRAB_PRODUCTS = ['nexmo_j1', 'j1', 'nexmo_dana', 'nexmo_turbo']


class PaymentMethodImpactedType(object):
    PRIMARY = 'Primary'
    BACKUP = 'Backup'
    PRIMARY_AND_BACKUP = 'Primary and Backup'


class WorkflowConst(object):
    JULO_ONE = 'JuloOneWorkflow'
    JULO_STARTER = 'JuloStarterWorkflow'
    JULO_ONE_IOS = 'JuloOneIOSWorkflow'
    GRAB = 'GrabWorkflow'
    MERCHANT_FINANCING_WORKFLOW = 'MerchantFinancingWorkflow'
    JULOVER = 'JuloverWorkflow'
    CREDIT_CARD = 'CreditCardWorkflow'
    DANA = 'DanaWorkflow'
    PARTNER = 'PartnerWorkflow'  # for Axiata
    LEGACY = 'LegacyWorkflow'
    MF_STANDARD_PRODUCT_WORKFLOW = (
        'PartnershipMfWebAppWorkflow'  # MF Standard Workflow (Axiata Included)
    )
    JULO_ONE_IOS = 'JuloOneIOSWorkflow'

    @classmethod
    def specific_partner_for_account_reactivation(cls):
        return (cls.DANA,)


class BucketConst(object):
    BUCKET_1_DPD = {'from': 1, 'to': 10}
    BUCKET_1_DPD_DANA = {'from': 5, 'to': 10}
    BUCKET_2_DPD = {'from': 11, 'to': 40}
    BUCKET_3_DPD = {'from': 41, 'to': 70}
    BUCKET_4_DPD = {'from': 71, 'to': 90}
    BUCKET_5_DPD = 91
    BUCKET_5_END_DPD = 180

    '''
        for Dana AiRudder
        DPD 0 - 5 call by Robocall
        DPD 6 - 180 call by AiRudder
    '''
    BUCKET_DPD_DANA_CASHLOAN = {'from': 0, 'to': 30}
    BUCKET_DPD_DANA_CICIL = {'from': 6, 'to': 30}
    BUCKET_DPD_DANA_SIM = {'from': 31, 'to': 60}
    BUCKET_DPD_DANA_PEPPER = {'from': 61, 'to': 90}
    BUCKET_DPD_DANA_91_PLUS = {'from': 91, 'to': 180}

    BUCKET_6_1_DPD = {'from': 181, 'to': 270}
    BUCKET_6_2_DPD = {'from': 271, 'to': 360}
    BUCKET_6_3_DPD = {'from': 361, 'to': 720}
    BUCKET_6_4_DPD = 721
    EXCLUDE_RELEASE_DATE = '2020-10-5'  # date need to be change when release
    BUCKET_RANGES = [
        (range(1, 11), 1),
        (range(11, 41), 2),
        (range(41, 71), 3),
        (range(71, 91), 4),
        (range(91, 181), 5),
        (range(181, 271), 6.1),
        (range(271, 361), 6.2),
        (range(361, 721), 6.3),
    ]


class CommsConst(object):
    PN = 'pn'
    EMAIL = 'email'
    SMS = 'sms'
    COOTEK = 'cootek'
    ROBOCALL = 'robocall'


class EmailDeliveryAddress(object):
    COLLECTIONS_JTF = 'collections@julo.co.id'
    COLLECTIONS_JTP = 'collections@juloperdana.co.id'
    LEGAL_JTF = 'departemen.hukum@julo.co.id'
    LEGAL_JTP = 'departemen.hukum@juloperdana.co.id'
    CS_JULO = 'cs@julo.co.id'
    LEGAL_THIRD_PARTY = 'lawoffice@kaldlaw.id'
    REPAYMENT_NOREPLY = 'repayment-noreply@julo.co.id'


class AutoDebetComms:
    SMS_DPDS = (-7, -3, -1)
    EMAIL_DPDS = (-2,)
    PN_DPDS = (-5, -4, -3, -2, -1)


class UploadAsyncStateType(object):
    JULOVERS = "JULOVERS"
    EMPLOYEE_FINANCING = "EMPLOYEE_FINANCING"
    EMPLOYEE_FINANCING_DISBURSEMENT = "EMPLOYEE_FINANCING_DISBURSEMENT"
    EMPLOYEE_FINANCING_REPAYMENT = "EMPLOYEE_FINANCING_REPAYMENT"
    EMPLOYEE_FINANCING_PRE_APPROVAL = "EMPLOYEE_FINANCING_PRE_APPROVAL"
    EMPLOYEE_FINANCING_SEND_APPLICATION_FORM_URL = "EMPLOYEE_FINANCING_SEND_APPLICATION_FORM_URL"
    EMPLOYEE_FINANCING_SEND_DISBURSEMENT_FORM_URL = "EMPLOYEE_FINANCING_SEND_DISBURSEMENT_FORM_URL"
    DANA_LOAN_SETTLEMENT = "DANA_LOAN_SETTLEMENT"
    MERCHANT_FINANCING_DISBURSEMENT = "MERCHANT_FINANCING_DISBURSEMENT"
    MERCHANT_FINANCING_REGISTER = "MERCHANT_FINANCING_REGISTER"
    MERCHANT_FINANCING_ADJUST_LIMIT = "MERCHANT_FINANCING_ADJUST_LIMIT"
    DANA_UPDATE_PUSDAFIL_DATA = "DANA_UPDATE_PUSDAFIL_DATA"
    VENDOR_RPC_DATA = "VENDOR_RPC_DATA"
    RUN_FDC_INQUIRY_CHECK = "RUN_FDC_INQUIRY_CHECK"
    AGENT_ASSISTED_PRE_CHECK_USER = "AGENT_ASSISTED_PRE_CHECK_USER"
    AGENT_ASSISTED_SCORING_USER_DATA = "AGENT_ASSISTED_SCORING_USER_DATA"
    AGENT_ASSISTED_FDC_PRE_CHECK_USER = "AGENT_ASSISTED_FDC_PRE_CHECK_USER"
    AGENT_ASSISTED_COMPLETE_DATA_STATUS_UPDATE = "AGENT_ASSISTED_COMPLETE_DATA_STATUS_UPDATE"
    PRODUCT_FINANCING_LOAN_CREATION = "PRODUCT_FINANCING_LOAN_CREATION"
    PRODUCT_FINANCING_LOAN_DISBURSEMENT = "PRODUCT_FINANCING_LOAN_DISBURSEMENT"
    PRODUCT_FINANCING_LOAN_REPAYMENT = "PRODUCT_FINANCING_LOAN_REPAYMENT"
    PRODUCT_FINANCING_LENDER_APPROVAL = "PRODUCT_FINANCING_LENDER_APPROVAL"
    MF_STANDARD_CSV_LOAN_UPLOAD = "MF_STANDARD_CSV_LOAN_UPLOAD"


class UploadAsyncStateStatus(object):
    WAITING = "waiting"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    PARTIAL_COMPLETED = "partial_completed"


class EmailReminderModuleType(object):
    EMPLOYEE_FINANCING = 'EF'
    OTHER = 'OTHER'


class EmailReminderType(object):
    REPAYMENT = 'REPAYMENT'
    OTHER = 'OTHER'


class CheckoutExperienceExperimentGroup(object):
    CONTROL_GROUP = 'control group'
    EXPERIMENT_GROUP_1 = 'experiment group 1'
    EXPERIMENT_GROUP_2 = 'experiment group 2'


class OnboardingIdConst:
    """
    LFS as LongForm Shortened
    LF as LongForm
    """

    LONGFORM_ID = 1
    SHORTFORM_ID = 2
    LONGFORM_SHORTENED_ID = 3
    LF_REG_PHONE_ID = 4
    LFS_REG_PHONE_ID = 5
    LFS_SPLIT_EMERGENCY_CONTACT = 9

    # Experiment Purpose
    JULO_STARTER_FORM_ID = 6

    # Julo Starter Product
    JULO_STARTER_ID = 7
    JULO_360_EXPERIMENT_ID = 8
    JULO_360_J1_ID = 10
    JULO_360_TURBO_ID = 11

    JULO_TURBO_IDS = [JULO_STARTER_ID, JULO_360_TURBO_ID]
    JULO_360_IDS = [JULO_360_J1_ID, JULO_360_TURBO_ID]
    MSG_NOT_ALLOWED = 'Onboarding is not allowed!'

    # for default
    ONBOARDING_DEFAULT = LONGFORM_ID


class ApiLoggingConst:
    LOG_REQUEST = 'request'
    LOG_RESPONSE = 'response'
    LOG_HEADER = 'header'


class SkiptraceResultChoiceConst:
    RPC = 'RPC'
    WPC = 'WPC'
    CANCEL = 'Cancel'
    REJECTED = 'Rejected/Busy'
    NO_ANSWER = 'No Answer'
    NOT_CONNECTED = 'Not Connected'

    @classmethod
    def basic_skiptrace_result_list(cls):
        return [
            cls.NOT_CONNECTED,
            cls.REJECTED,
            cls.NO_ANSWER,
            cls.WPC,
            cls.RPC,
        ]


class PTPStatus(object):
    PAID = "Paid"
    PAID_AFTER_PTP_DATE = "Paid after ptp date"
    PARTIAL = 'Partial'
    NOT_PAID = 'Not Paid'

    BROKEN_PROMISE_STATUS = (PAID_AFTER_PTP_DATE, NOT_PAID)


class BNIVAConst(object):
    MAX_LIMIT = 999999
    COUNT_LIST = [980000, 990000, MAX_LIMIT]


class FeatureSettingMockingProduct:
    J_STARTER = 'j-starter'


class AlicloudNoRetryErrorCodeConst:
    OK = 'OK'
    NOT_SUPPORTED_COUNTRY = 'NOT_SUPPORTED_COUNTRY'
    ALERT_LIMIT_DAY = 'ALERT_LIMIT_DAY'
    ALERT_LIMIT_MONTH = 'ALERT_LIMIT_MONTH'
    CONTENT_EXCEED_LIMIT = 'CONTENT_EXCEED_LIMIT'
    MOBILE_NUMBER_ILLEGAL = 'MOBILE_NUMBER_ILLEGAL'


class PushNotificationLoanEvent:
    LOAN_SUCCESS_X220 = 'loan_success_x220'


class PushNotificationDowngradeAlert:
    DOWNGRADE_INFO_ALERT = 'downgrade_info_alert'


class PushNotificationPointChangeAlert:
    POINT_CHANGE_ALERT = 'point_change_alert'


class PNBalanceConsolidationVerificationEvent:
    APPROVED_STATUS_EVENT = 'balance_consolidation_verification_approved'


class ApplicationStatusChange:
    DUPLICATE_PHONE = 'Nomor tidak dapat diubah karena telah digunakan oleh customer lain'


class XidIdentifier(Enum):
    APPLICATION = 1
    LOAN = 2


class InAppPTPDPD:
    DPD_START_APPEAR = -7
    DPD_STOP_APPEAR = -1


class MycroftThresholdConst(object):
    NO_FDC_BPJS_EL_MYCROFT = 0.8


class NewCashbackReason(object):
    PAID_BEFORE_TERMS = 'Paid before cashback terms'
    PAID_AFTER_TERMS = 'Paid after cashback terms'
    PAID_REFINANCING = 'Paid with Refinancing'
    PAID_WAIVER = 'Paid with waiver'
    PAYMENT_REVERSE = 'Payment Void Reverse'


class NewCashbackConst(object):
    MAX_CASHBACK_COUNTER = 5
    # this list status for decide cashback counter
    NORMAL_STATUS = 'normal'
    PASSED_STATUS = 'passed due'
    REFINANCING_STATUS = 'refinancing'
    WAIVER_STATUS = 'waiver'
    ZERO_PERCENTAGE_STATUS = 'zero cashback pct'
    ACCOUNT_STATUS_SUSPENDED = 'suspended'


class PaymentEventConst(object):
    PAYMENT = 'payment'
    PAYMENT_VOID = 'payment_void'
    CUSTOMER_WALLET = 'customer_wallet'
    CUSTOMER_WALLET_VOID = 'customer_wallet_void'
    PARTIAL_PAYMENT_TYPES = [
        PAYMENT, PAYMENT_VOID, CUSTOMER_WALLET, CUSTOMER_WALLET_VOID
    ]


class FaQSectionNameConst(object):
    CASHBACK_NEW_SCHEME = 'cashback_new_scheme'
    CASHBACK_NEW_SCHEME_EXPERIMENT = 'cashback_new_scheme_experiment'


class CommsRetryFlagStatus(object):
    START = 0
    ITERATION = 1
    FINISH = 2

class VariableStorageKeyConst(object):
    WARNING_LETTER_EXT_NUMBER = 'warning_letter_ext_number'


class RedisLockKeyName(object):
    UPDATE_ACCOUNT_CYCLE_DAY_HISTORY = 'update_account_cycle_day_history'
    CREATE_FDC_REJECTED_LOAN_TRACKING = 'create_fdc_rejected_loan_tracking'
    CREATE_LOAN_DBR_LOG = 'create_loan_dbr_log'
    HANDLE_MAYBE_GTL_INSIDE_STATUS_AND_NOTIFY = 'handle_maybe_gtl_inside_status_and_notify'
    UPDATE_MISSION_CRITERIA_WHITELIST = 'update_mission_criteria_whitelist'
    UPDATE_TRANSACTION_MISSION_PROGRESS = 'update_transaction_mission_progress'
    RATE_LIMITER = 'rate_limiter'
    CREATE_LOYALTY_POINT = 'create_loyalty_point'
    STORE_FAMA_REPAYMENT_APPROVAL_DATA = 'store_fama_repayment_approval_data'
    APPROVE_LOAN_FOR_CHANNELING = 'approve_loan_for_channeling'

    @classmethod
    def list_key_name(cls):
        return (
            cls.UPDATE_ACCOUNT_CYCLE_DAY_HISTORY,
            cls.CREATE_FDC_REJECTED_LOAN_TRACKING,
            cls.CREATE_LOAN_DBR_LOG,
            cls.HANDLE_MAYBE_GTL_INSIDE_STATUS_AND_NOTIFY,
            cls.UPDATE_MISSION_CRITERIA_WHITELIST,
            cls.UPDATE_TRANSACTION_MISSION_PROGRESS,
            cls.RATE_LIMITER,
            cls.CREATE_LOYALTY_POINT,
            cls.STORE_FAMA_REPAYMENT_APPROVAL_DATA,
            cls.APPROVE_LOAN_FOR_CHANNELING,
        )

    @classmethod
    def key_name_exists(cls, key_name):
        return key_name in cls.list_key_name()


class CSVWhitelistFileValidatorConstant(object):
    # Customer
    CUSTOMER_ID_LENGTH = 10
    CUSTOMER_ID_PREFIX = "1"


class FeatureBSSRefinancing(object):
    FEATURE_NAME = 'bss_refinancing_r4'
    FEATURE_CATEGORY = 'bss_refinancing'
    FEATURE_DESCRIPTION = 'bss refinancing R4'


class TokenRefreshNameConst(object):
    REPAYMENT_GOOGLE_ACCOUNT = "repayment_google_account"
    DATA_GOOGLE_ACCOUNT = "data_google_account"
    PARTNERSHIP_GOOGLE_ACCOUNT = "partnership_google_account"
    COLLECTION_GOOGLE_ACCOUNT = "collection_google_account"


class TokenRefreshScopeConst(object):
    GOOGLE_DRIVE = "google_drive"


class CloudStorage:
    OSS = "oss"  # alibaba
    GCS = "gcs"  # google cloud storage
    S3 = "s3"  # amazon


class IdentifierKeyHeaderAPI:

    X_DEVICE_ID = 'HTTP_X_DEVICE_ID'
    X_PLATFORM = 'HTTP_X_PLATFORM'
    X_PLATFORM_VERSION = 'HTTP_X_PLATFORM_VERSION'

    ANDROID_KEY = 'ANDROID'
    IOS_KEY = 'iOS'

    KEY_IOS_DECORATORS = 'device_ios_user'


class JuloCompanyContacts:
    COMPANY_PHONE_NUMBERS = [
        "02150919034",
        "02150919035",
        "02150919036",
        "02150919037",
        "02130433659",
    ]
