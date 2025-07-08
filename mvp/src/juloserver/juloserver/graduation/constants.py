class FeatureNameConst(object):
    GRADUATION_REGULAR_CUSTOMER = "graduation_regular_customer"
    GRADUATION_FDC_CHECK = 'graduation_fdc_check'
    GRADUATION_NEW_FLOW = "graduation_new_flow"
    CUSTOMER_SUSPEND = 'customer_suspend'
    DOWNGRADE_DATE_PERIOD = 60
    DOWNGRADE_INFO_ALERT = 'downgrade_info_alert'
    DOWNGRADE_CRITERIA_CONFIG_FS = 'downgrade_criteria_config'


class GraduationRules:
    LIMIT_UTILIZATION = 0.9
    CLCS_PRIME_SCORE = 0.95


class DefaultLimitClass:
    ONE_MILLION = 1000000
    FIVE_MILLION = 5000000
    TEN_MILLION = 10000000


class RiskCategory:
    LESS_RISKY = 'less_risky'
    RISKY = 'risky'


class GraduationAdditionalLimit:
    ONE_MILLION = 1000000
    TWO_MILLION = 2000000
    FOUR_MILLION = 4000000


class GraduationType:
    ENTRY_LEVEL = 'entry_level'
    REGULAR_CUSTOMER = 'regular_customer'
    BALANCE_CONSOLIDATION = 'balance_consolidation'


class DowngradeType:
    BALCON_PUNISHMENTS = 'balcon_punishments'


class CustomerSuspendRedisConstant:
    CUSTOMER_SUSPEND = 'customer_suspend_v2.{}'
    REDIS_CACHE_TTL_DEFAULT_HOUR = 24


class GraduationRedisConstant:
    MAX_CUSTOMER_GRADUATION_ID = 'max_customer_graduation_id.{}'


class GraduationFailureType:
    GRADUATION = 'graduation'
    DOWNGRADE = 'downgrade'


class CustomerSuspendType:
    SUSPENDED = 'suspended'
    UNSUSPENDED = 'unsuspended'


class GraduationFailureConst:
    MAX_RETRIES = 3
    FAILED_BY_MAX_LIMIT = 'failed_by_max_limit'
    FAILED_BY_SET_LIMIT = 'failed_by_set_limit'


class DowngradeInfoRedisConst:
    DOWNGRADE_INFO_ALERT = 'downgrade_info_alert_customer_id_.{}'
    REDIS_CACHE_TTL_DEFAULT_HOUR = 24
