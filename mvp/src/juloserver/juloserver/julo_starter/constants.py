from juloserver.julo.models import ApplicationStatusCodes


class ApplicationExpiredJStarter:
    TARGET_EXPIRED_DAYS = 90
    MESSAGE_FOR_REASON = "system_triggered"


class JuloStarterFormExtraResponseCode:
    SUCCESS = 'success'
    FAILED = 'failed'
    APPLICATION_NOT_ALLOW = 'application_not_allow'
    APPLICATION_NOT_FOUND = 'application_not_found'
    USER_NOT_ALLOW = 'user_not_allow'
    DUPLICATE_PHONE = 'duplicate_phone'


class JuloStarterFormExtraResponseMessage:
    SUCCESS = 'success'
    APPLICATION_NOT_ALLOW = 'Application is not allowed'
    APPLICATION_NOT_FOUND = 'Application not found'
    USER_NOT_ALLOW = 'User is not allowed'
    DUPLICATE_PHONE = 'Nomor Handphone Tidak Boleh Sama'


class JuloStarterSecondCheckResponseCode:
    APPLICATION_NOT_FOUND = 'application_not_found'
    USER_NOT_ALLOWED = 'user_not_allowed'
    NOT_YET_SECOND_CHECK = 'not_yet_second_check'
    ON_SECOND_CHECK = 'on_second_check'
    DUKCAPIL_FAILED = 'dukcapil_failed'
    HEIMDALL_FAILED = 'heimdall_failed'
    FINISHED_SECOND_CHECK = 'finished_second_check'


class JuloStarterFlow:
    FULL_DV = 'full_dv'
    PARTIAL_LIMIT = 'partial_limit'


class JuloStarter190RejectReason:
    REJECT_DV = 'LOC rejected by DV'
    REJECT_FRAUD = 'LOC rejected by fraud'
    REJECT = 'LOC account reject'
    REJECT_BINARY = 'LOC rejected by binary check'
    REJECT_DYNAMIC = 'LOC rejected by dynamic check'
    REJECT_LOW_DUKCAPIL_FR = 'rejected by Dukcapil FR too low'
    REJECT_HIGH_DUKCAPIL_FR = 'rejected by Dukcapil FR too high'
    REJECT_DUKCAPIL_FR = 'LOC rejected by dukcapil FR'
    REJECTED = 'LOC Rejected'


class JuloStarterDukcapilCheck:
    PASSED = 1
    BYPASS = 2
    NOT_PASSED = 3


class PushNotificationJStarterConst:

    # Code template for section process checks and scoring
    CODE_TEMPLATE_OK = 'check_scoring_result_ok'
    CODE_TEMPLATE_OFFER = 'check_scoring_result_offer'
    CODE_TEMPLATE_REJECTED = 'check_scoring_result_rejected'

    DESTINATION_TEMPLATE_OK = 'julo_starter_second_check_ok'
    DESTINATION_TEMPLATE_OFFER = 'julo_starter_eligbility_j1_offer'
    DESTINATION_TEMPLATE_REJECTED = 'julo_starter_second_check_rejected'


class NotificationSetJStarter:

    # check_scoring_result_ok
    KEY_MESSAGE_OK = 'dukcapil_true_heimdall_true'
    KEY_MESSAGE_OK_FULL_DV = 'dukcapil_true_heimdall_true_full_dv'

    # check_scoring_result_offer
    KEY_MESSAGE_OFFER = 'dukcapil_true_heimdall_false'

    # check_scoring_result_rejected
    KEY_MESSAGE_REJECTED = 'dukcapil_false'

    # user receive full limit after pending
    KEY_MESSAGE_FULL_LIMIT = 'full_limit'

    # Parameters keys in table
    KEY_TITLE = 'title'
    KEY_BODY = 'body'
    KEY_DESTINATION = 'destination'


class JStarterToggleConst:
    """
    Configure constant to match condition from Android
    To check enabled configuration
    :go to application form as value 0
    :go to product picker as value 1
    """

    GO_TO_APPLICATION_FORM = 0
    GO_TO_PRODUCT_PICKER = 1

    # this parameter should be match with Firebase setting
    KEY_PARAM_TOGGLE = "jstar_toggle"


class JuloStarterSecondCheckConsts:

    NOT_YET_STATUSES = (
        ApplicationStatusCodes.NOT_YET_CREATED,
        ApplicationStatusCodes.FORM_CREATED,
        ApplicationStatusCodes.FORM_PARTIAL_EXPIRED,
        ApplicationStatusCodes.APPLICATION_CANCELED_BY_CUSTOMER,
    )

    REJECTED_STATUSES = (
        ApplicationStatusCodes.APPLICATION_DENIED,
        ApplicationStatusCodes.APPLICATION_FLAGGED_FOR_FRAUD,
    )

    ON_PROGRESS_STATUSES = (
        ApplicationStatusCodes.FORM_PARTIAL,
        ApplicationStatusCodes.JULO_STARTER_AFFORDABILITY_CHECK,
    )

    # This key should be match in FE (Android)
    KEY_NOT_YET = 'not_yet'

    # this key, FE (Android) will be stay in Animation C
    # and this process without reach to Sphinx process
    KEY_ON_PROGRESS = 'on_progress'

    # This key, FE (Android) will be stay in Animation C
    # and will trigger FE to start emulator check
    KEY_SPHINX_PASSED = 'sphinx_passed'

    KEY_NOT_PASSED = 'not_passed'
    KEY_FINISHED = 'finished'
    KEY_FINISHED_FULL_DV = 'finished_full_dv'
    KEY_OFFER_REGULAR = 'offer_regular'


class BinaryCheckFields:
    bypass = [
        'own_phone',
        'monthly_income',
        'job_term_gt_3_month',
        'debt_to_income_40_percent',
        'basic_savings',
        'job_not_black_listed',
        'saving_margin',
        'loan_purpose_description_black_list',
        'dynamic_check',
        'inside_premium_area',
    ]

    exclude = [
        'own_phone',
        'dynamic_check',
        'inside_premium_area',
        'saving_margin',
    ]


class JobsConst:
    IBU_RUMAH_TANGGA = 'Ibu rumah tangga'
    STAF_RUMAH_TANGGA = 'Staf rumah tangga'
    TIDAK_BEKERJA = 'Tidak bekerja'
    MAHASISWA = 'Mahasiswa'
    JOBLESS_CATEGORIES = {TIDAK_BEKERJA, STAF_RUMAH_TANGGA, IBU_RUMAH_TANGGA, MAHASISWA}


class SphinxThresholdNoBpjsConst:

    MEDIUM_SCORE_THRESHOLD = 'medium_score_threshold'
    MEDIUM_SCORE_OPERATOR = 'medium_score_operator'

    HIGH_SCORE_THRESHOLD = 'high_score_threshold'
    HIGH_SCORE_OPERATOR = 'high_score_operator'

    HOLDOUT = 'holdout'


class BpjsHoldoutConst:

    # for logging
    KEY_PROCEED = 'proceed_to'
    KEY_COUNTER = 'counter'


class JuloStarterFieldExtraForm:

    FIELDS = (
        'job_type',
        'job_industry',
        'job_description',
        'company_name',
        'payday',
        'marital_status',
        'close_kin_name',
        'close_kin_mobile_phone',
        'kin_relationship',
        'kin_name',
        'kin_mobile_phone',
        'job_start',
        'last_education',
        'monthly_income',
        'spouse_name',
        'spouse_mobile_phone',
    )
