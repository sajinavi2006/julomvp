from builtins import object
from juloserver.julo.statuses import ApplicationStatusCodes


class JuloOneChangeReason(object):
    SONIC_AFFORDABILITY = 'SonicAffordability'
    HSFBP = 'high_score_full_bypass'
    NOT_REGULAR_VERIFICATION_CALLS_SUCCESSFUL_REASON = (SONIC_AFFORDABILITY, HSFBP)
    HIGH_C_SCORE_BY_PASS = 'Julo one pass high C score'
    MEDIUM_SCORE_BY_PASS = 'Julo one pass medium score'
    EMULATOR_DETECED = 'emulator_detected'
    UNDERPERFORMING_PARTNER = 'under performing partner'
    MYCROFT_FAIL = 'fail to pass Mycroft check'
    ASSISTED_SELFIE = 'selfie difotoin <=0.9 mycroft'
    PASS_SHOPEE_WHITELIST = 'pass Shopee whitelist'
    REVIVE = 'revive'
    RESCORE = 'rescore'
    BLACKLISTED_ASN_DETECTED = 'Blacklisted ASN detected'
    REVIVE_BY_GOOD_FDC = 'Revive By Good FDC'
    SHOPEE_SCORE_NOT_PASS = 'shopee score not pass by system'
    REVIVE_BY_TOKOSCORE = 'revive by tokoscore'
    BAD_HISTORY_CUSTOMER = 'bad history with JULO'
    NO_DSD_NO_FDC_FOUND = 'No DSD No FDC found'
    FORCE_HIGH_SCORE = "Force high score"
    CUSTOMER_TYPO_ACK = "customer_triggered_typo_acknowledged"
    CUSTOMER_MOTHER_ACK = "customer_triggered_mother_name"
    CUSTOMER_TYPO_MOTHER_ACK = "customer_triggered_mother_name_typo"
    FRAUD_CHANGE_REASON = "Prompted by the Anti Fraud API"


class JuloOne135Related(object):
    REAPPLY_AFTER_ONE_MONTHS_REASON_J1 = [
        'failed ca insuff income',
        'failed dv expired ktp',
        'failed dv identity',
        JuloOneChangeReason.SHOPEE_SCORE_NOT_PASS.lower(),
    ]
    REAPPLY_AFTER_THREE_MONTHS_REASON_J1 = [
        'outside coverage area',
        'failed dv min income not met',
        'failed dv income',
        'failed dv other',
        'job type blacklisted',
        'employer blacklisted',
        'cannot afford loan',
        'failed credit limit generation',
        JuloOneChangeReason.NO_DSD_NO_FDC_FOUND.lower(),
    ]
    REAPPLY_AFTER_HALF_A_YEAR_REASON_J1 = [
        'foto tidak senonoh',
    ]
    REAPPLY_AFTER_ONE_YEAR_REASON_J1 = [
        'negative payment history with julo',
        'negative data in sd',
        'bad history with julo',
    ]
    REAPPLY_NOT_ALLOWED_REASON_J1 = ['fraud report']
    ALL_BANNED_REASON_J1 = (
        REAPPLY_AFTER_ONE_MONTHS_REASON_J1
        + REAPPLY_AFTER_THREE_MONTHS_REASON_J1
        + REAPPLY_AFTER_HALF_A_YEAR_REASON_J1
        + REAPPLY_AFTER_ONE_YEAR_REASON_J1
        + REAPPLY_NOT_ALLOWED_REASON_J1
        + ['age not met']
    )
    REJECTION_135_CHANGE_REASONS = [
        'failed pv employer',
        'cannot afford loan',
        'failed pv applicant',
    ]
    REJECTION_135_PVE_PVA_CHANGE_REASONS = REJECTION_135_CHANGE_REASONS + [
        'employer blacklisted',
    ]
    REJECTION_135_DV_CHANGE_REASONS = REJECTION_135_CHANGE_REASONS + [
        'failed dv other',
    ]
    ALL_REJECTED_REFERRAL_CODE = ['mdjulo', 'mduckjulo']


class ApplicationTagList(object):
    ALL = [
        'is_hsfbp',
        'is_mandatory_docs',
        'is_dv',
        'is_sonic',
        'is_pve',
        'is_pva',
        'is_ca',
        'is_ac',
        'is_doc_resubmission',
        'is_bpjs_bypass',
        'is_bpjs_entrylevel',
        'is_vcdv',
        'is_tokoscore_revive',
        'is_checked_repopulate_zipcode',
    ]


class PartnerNameConstant(object):
    CERMATI = "cermati"
    OLX = "olx"
    CEKAJA = "cekaja"
    J1 = 'j1'
    USAHAKU99 = '99usahaku'
    GENERIC = "generic"
    MONEYDUCK = "moneyduck"
    LINKAJA = "linkaja"
    FINFLEET = 'finfleet'
    VOSPAY = "vospay"
    KLAR = "klar"
    KLOP = "klop"
    SELLURY = "sellury"
    DANA = "dana"
    DANA_CASH_LOAN = "dana_cash_loan"
    AXIATA_WEB = "axiata_web"
    SMARTFREN = "smartfren"
    JEFF = "jeff"
    GRAB = "grab"
    IOH_MYIM3 = "myim3"
    IOH_BIMA_PLUS = "bima"
    AMAR = 'amar'
    QOALA = 'qoala'
    AYOKENALIN = 'ayokenalin'
    NEX = 'nex'
    QOALASPF = 'qoalaspf'  # Qoala  smartphone financing

    @classmethod
    def list_partnership_web_view(cls):
        return [cls.LINKAJA]

    @classmethod
    def qris_partners(cls):
        return [cls.AMAR]


class AddressFraudPreventionConstants:
    DISTANCE_RADIUS_LIMIT_KM = 150


class ApplicationRiskyDecisions(object):
    NO_DV_BYPASS_AND_NO_PVE_BYPASS = 'NO DV BYPASS AND NO PVE BYPASS'
    NO_DV_BYPASS = 'NO DV BYPASS'
    NO_PVE_BYPASS = 'NO PVE BYPASS'

    @classmethod
    def all(cls):
        return [cls.NO_DV_BYPASS_AND_NO_PVE_BYPASS, cls.NO_DV_BYPASS, cls.NO_PVE_BYPASS]

    @classmethod
    def no_dv_bypass(cls):
        return [cls.NO_DV_BYPASS_AND_NO_PVE_BYPASS, cls.NO_DV_BYPASS]

    @classmethod
    def no_pve_bypass(cls):
        return [cls.NO_DV_BYPASS_AND_NO_PVE_BYPASS, cls.NO_PVE_BYPASS]


class ExperimentJuloStarterKeys:
    REGULAR = 'regular_customer_id'
    JULOSTARTER = 'julo_starter_customer_id'
    TARGET_VERSION = 'target_version'

    # Group name Experiment for Regular Flow
    GROUP_REGULAR = 'experiment regular'

    # Group name Experiment for Non Regular Flow
    # Like JuloStarter / onboarding_id = 6
    GROUP_NON_REGULAR = 'experiment non regular'


class GooglePlayIntegrityConstants:
    MAX_NO_OF_RETRIES = 5
    MAXIMUM_BACKOFF_TIME = 65
    JS_MAX_NO_OF_RETRIES = 3
    JS_RETRY_BACKOFF = 1


class ImageKtpConstants:
    MIN_KTP_RATIO = 1.55
    MAX_KTP_RATIO = 1.75
    MIN_KTP_RESOLUTION = 139500


class CacheKey:
    SHOPEE_REJECT_HOLDOUT_COUNTER = 'shopee-reject-holdout-counter'
    BPJS_NO_FOUND_HOLDOUT_COUNTER = 'bpjs-no-found-holdout-counter'
    CREDIT_LIMIT_ADJUSTMENT_HOLDOUT_COUNTER = "credit-limit-adjustment-holdout-counter"
    BANK_STATEMENT_CLIENT_HOLDOUT_COUNTER = "bank-statement-client-holdout-counter"
    LBS_MIN_AFFORDABILITY_BYPASS_COUNTER = 'lbs-min-affordability-bypass-counter'
    LBS_SWAPOUT_DUKCAPIL_BYPASS_COUNTER = 'lbs-swapout-dukcapil-bypass-counter'
    LANNISTER_EXPERIMENT_COUNTER = 'lannister-experiment-counter'
    HSFBP_SESSION_PREFIX = 'hsfbp_session_check_{}'


class BankStatementConstant:
    IS_AVAILABLE_BANK_STATEMENT_ALL = 'is_available_bank_statement_all'
    IS_AVAILABLE_BANK_STATEMENT_EMAIL = 'is_available_bank_statement_email'


class ApplicationStatusExpired:

    # List application will be reapply with endpoint reapply
    # x106, x135, x136, x139
    STATUS_CODES = (
        ApplicationStatusCodes.APPLICATION_DENIED,
        ApplicationStatusCodes.FORM_PARTIAL_EXPIRED,
        ApplicationStatusCodes.RESUBMISSION_REQUEST_ABANDONED,
        ApplicationStatusCodes.VERIFICATION_CALLS_EXPIRED,
        ApplicationStatusCodes.APPLICATION_CANCELED_BY_CUSTOMER,
    )


class ApplicationStatusEventType:
    APPSFLYER = 'appsflyer'
    GA = 'ga'
    APPSFLYER_AND_GA = 'appsflyer_and_ga'


class ApplicationStatusAppsflyerEvent:
    # for application with certain pgood
    APPLICATION_X105_PCT70 = 'x_105_pct70'
    APPLICATION_X105_PCT80 = 'x_105_pct80'
    APPLICATION_X105_PCT90 = 'x_105_pct90'
    APPLICATION_X190_PCT70 = 'x_190_pct70'
    APPLICATION_X190_PCT80 = 'x_190_pct80'
    APPLICATION_X190_PCT90 = 'x_190_pct90'
    APPLICATION_X100_DEVICE = 'x_100_device'
    APPLICATION_X105_BANK = 'x_105_bank'

    APPLICATION_X105_PCT80_MYCROFT_90 = '105_p80_mycroft90'
    APPLICATION_X105_PCT90_MYCROFT_90 = '105_p90_mycroft90'
    APPLICATION_X190_PCT80_MYCROFT_90 = '190_p80_mycroft90'
    APPLICATION_X190_PCT90_MYCROFT_90 = '190_p90_mycroft90'


class FraudBankAccountConst:
    # use mapping for further development

    # mapping is {'prefix': 'bank_code'}
    REJECTED_BANK_ACCOUNT_NAMES = {'100451': '002'}  # BRI

    # mapping is {'prefix': 'change reason'}
    REJECTED_BANK_ACCOUNT_MESSAGE = {
        '100451': "fraud attempt: BRI digital bank",  # BRI VA
    }


class ApplicationDsdMessageConst:

    FLAG_STATUS_IS_NOT_X105 = 'status_is_not_x105'
    MSG_NOT_IN_X105 = 'Status is not in x105'

    FLAG_NOT_J1_JTURBO = 'not_j1_jturbo'
    MSG_NOT_J1_JTURBO = 'This application is not J1 or JTurbo'

    FLAG_AVAILABLE_CREDIT_SCORE = 'available_credit_score'
    MSG_AVAILABLE_CREDIT_SCORE = 'Credit Score already generated'

    FLAG_AVAILABLE_PGOOD_SCORE = 'available_pgood_score'
    MSG_AVAILABLE_PGOOD_SCORE = 'Pgood Score already generated'

    FLAG_AVAILABLE_ETL_STATUS = 'available_etl_status'
    MSG_NEED_RAISE_TO_PRE = 'Please raise to PRE and create ESCard'

    FLAG_WAIT_FEW_MINUTES = 'not_available_cust_app_action'
    MSG_TO_WAIT_FEW_MINUTES = 'Ask customer wait 30 minutes then logout and login again'

    FLAG_WAIT_FEW_HOURS = 'wait_few_hours'
    MSG_TO_WAIT_FEW_HOURS = (
        'Wait 12 hours, then open this feature again, then check this app_id again'
    )

    FLAG_NOT_AVAILABLE_FDC = 'not_available_fdc'
    MSG_ALREADY_MOVE_STATUS = 'Moving application to status expired (x106)'

    FLAG_SUCCESS_ALL_CHECK = 'success_all_check'

    MSG_X105_LESS_THAN_FEW_MINUTES = (
        'Please wait 30 minutes since this application move to x105. '
        'If score not generated yet/not moved to x106 (for J1), '
        'please raise to PRE and create ESCard',
    )

    LIST_OF_FLAG_SKIP_PROCESS = [
        FLAG_NOT_J1_JTURBO,
        FLAG_STATUS_IS_NOT_X105,
        FLAG_NOT_AVAILABLE_FDC,
    ]

    LIST_OF_FLAG_DONT_ALLOW_RESCRAPE = [
        FLAG_WAIT_FEW_HOURS,
        FLAG_SUCCESS_ALL_CHECK,
        FLAG_AVAILABLE_ETL_STATUS,
    ]


class AgentAssistedSubmissionConst:

    TAG_NAME = 'is_agent_assisted_submission'
    TAG_STATUS = 1

    STATUS_IN_NEO_BANNER = '105_IS_AGENT_ASSISTED_SUBMISSION'


class AnaServerFormAPI:

    COMBINED_FORM = '/api/amp/v1/combined-form/'
    SHORT_FORM = '/api/amp/v1/short-form/'
    IOS_FORM = '/api/amp/v1/ios-form'


class InstructionVerificationConst:

    PAYSLIP = 'payslip'
    BANK_STATEMENT = 'bank_statement'


class HSFBPIncomeConst:

    DECLINED_TAG = 'is_hsfbp_decline_doc'
    EXPIRED_TAG = 'is_hsfbp_no_doc'
    GOOD_DOC_TAG = 'is_hsfbp_good_doc'
    BAD_DOC_TAG = 'is_hsfbp_bad_doc'

    CHANGE_REASON_SUBMIT_DOCS = 'hsfbp_income_submitted'
    CHANGE_REASON_GOOD_DOCS = 'Good_income_verification_document'
    CHANGE_REASON_BAD_DOCS = 'Bad_income_verification_document'

    KEY_LAST_DIGIT_APP_ID = 'app_id'
    KEY_EXPIRATION_DAY = 'x120_hsfbp_expiry'
    KEY_ANDROID_APP_VERSION = 'android_app_version'

    KEY_EXP_CONTROL = 'control'
    KEY_EXP_EXPERIMENT = 'experiment'

    ACCEPTED_REASON = 'hsfbp_income_submitted'

    # this redis waiting count
    REDIS_EXPIRED_IN_SECONDS = 40
