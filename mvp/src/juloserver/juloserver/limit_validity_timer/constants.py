class LimitValidityTimerConsts:
    LIMIT_VALIDITY_TIMER_REDIS_KEY = 'limit_validity_timer_customers.{}'


class WhitelistCSVFileValidatorConsts:
    ALLOWED_EXTENSIONS = ["csv"]
    MAX_FILE_SIZE = 1024 * 1024 * 2.5  # 2.5 MB
