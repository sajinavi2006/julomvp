class DbConnectionAlias:
    BUREAU_DB = 'bureau_db'
    COLLECTION = 'collection_db'
    DEFAULT = 'default'
    JULOPLATFORM_DB = 'juloplatform_db'
    LOAN_DB = 'loan_db'
    LOGGING_DB = 'logging_db'
    ONBOARDING_DB = 'onboarding_db'
    PARTNERSHIP_DB = 'partnership_db'
    PARTNERSHIP_GRAB_DB = 'partnership_grab_db'
    PARTNERSHIP_ONBOARDING_DB = 'partnership_onboarding_db'
    REPAYMENT = 'repayment_db'
    UTILIZATION_DB = 'utilization_db'

    @classmethod
    def transaction(cls):
        # will add loan_db when loan_db migrate
        return {cls.DEFAULT, cls.UTILIZATION_DB}

    @classmethod
    def utilization(cls):
        return {cls.DEFAULT, cls.UTILIZATION_DB}

    @classmethod
    def onboarding(cls):
        return {cls.DEFAULT, cls.ONBOARDING_DB}

    @classmethod
    def all(cls):
        return {
            cls.BUREAU_DB,
            cls.COLLECTION,
            cls.DEFAULT,
            cls.JULOPLATFORM_DB,
            cls.LOAN_DB,
            cls.LOGGING_DB,
            cls.ONBOARDING_DB,
            cls.PARTNERSHIP_DB,
            cls.PARTNERSHIP_GRAB_DB,
            cls.PARTNERSHIP_ONBOARDING_DB,
            cls.REPAYMENT,
            cls.UTILIZATION_DB,
        }


class RedisWhiteList:
    """
    Defined .csv file-names to be stored on cloud storage
    """

    BASE_WHITELIST_CSV_DIR = "redis_whitelist_csv"

    class Name:
        QRIS_CUSTOMER_IDS_WHITELIST = "qris_cutomer_ids_whitelist"

    class Key:
        SET_QRIS_WHITELISTED_CUSTOMER_IDS = 'set_qris_whitelisted_customer_ids'
        TEMP_SET_QRIS_WHITELISTED_CUSTOMER_IDS = 'temp_set_qris_whitelisted_customer_ids'

    class Status:
        PENDING = "pending"
        UPLOAD_SUCCESS = "upload_success"
        UPLOAD_FAILED = "upload_failed"
        WHITELIST_SUCCESS = "whitelist_success"
        WHITELIST_FAILED = "whitelist_failed"
        GENERAL_FAILED = "general_failed"


class AllConstMixin:
    """
    Mixin class to get all class method (string) values
    """

    @classmethod
    def all(cls):
        return {
            value
            for field_name, value in vars(cls).items()
            if (not field_name.startswith('_') and not callable(value) and isinstance(value, str))
        }
