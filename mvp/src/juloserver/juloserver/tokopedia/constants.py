from juloserver.julo.statuses import ApplicationStatusCodes


class TokoScoreConst:

    KEY_IS_ACTIVE_USERS = 'no_pg_dg'
    KEY_PAYLOAD_PHONE_NUMBER = 'phone_number'
    KEY_PAYLOAD_EMAIL = 'email'
    FLAG_REQUEST_IS_SUCCESS = 'success'

    # Score ID related with this
    # Tokoscore V4.1 Short = 160
    SCORE_ID = 160
    CONTRACT_ID = 363

    NOT_ALLOWED_STATUSES_FOR_REQUESTS = (ApplicationStatusCodes.FORM_CREATED,)

    # Experiment Setting Keys
    KEY_THRESHOLD = 'threshold'
    KEY_REQUIRE_MATCH = 'require_match'
    KEY_REQUIRE_ACTIVE = 'require_active'
    KEY_LIMIT_TOTAL_APP = 'limit_total_of_application'
    KEY_TOTAL_OF_PASSED = 'total_of_passed'

    KEY_PASSED = 'passed'
    KEY_NOT_PASSED = 'not_passed'

    # is application path tag
    TAG_NAME = 'is_tokoscore_revive'

    # define for passed tokoscore
    IS_PASSED = 1
    IS_NOT_PASSED = 0

    # For define score_type
    REVIVE_SCORE_TYPE = 'revive_score'
    SHADOW_SCORE_TYPE = 'shadow_score'

    # Credit Matrix Param
    CREDIT_MATRIX_PARAMETER = 'feature:tokoscore_whitelist'


class TokoScoreCriteriaConst:

    KEY_FDC_FETCH_FAIL = 'fail'
    KEY_FDC_FETCH_NOT_FOUND = 'not_found'
    KEY_FDC_FETCH_PASS = 'pass'

    KEY_BOTTOM_THRESHOLD = 'bottom_threshold'
    KEY_UPPER_THRESHOLD = 'upper_threshold'

    KEY_PACKAGE_NAME_TOKOPEDIA = 'com.tokopedia.tkpd'

    # for path tag status
    IS_PASSED_CRITERIA = 1

    CRITERIA_TAG_NAME = {
        'criteria_1': 'is_fail_heimdall_whitelisted_rescored',
        'criteria_2': 'is_no_fdc_whitelisted_rescored',
        'criteria_3': 'is_fail_mycroft_whitelisted_rescored',
    }
