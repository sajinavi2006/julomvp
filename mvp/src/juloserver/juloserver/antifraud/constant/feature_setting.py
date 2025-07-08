class BinaryCheck:
    class Parameter:
        HOLDOUT = "holdout"

        class Holdout:
            TYPE = "type"
            REGEX = "regex"
            PERCENTAGE = "percentage"
            PARTNER_IDS = "partner_ids"


class Dalnet:
    class ChildFeature:
        TELCO_RECORD_SCORE = "telco_record_score"


class GenericParameter:
    HOLDOUT = "holdout"
    FEATURES = "features"


class Holdout:
    class Type:
        INACTIVE = "inactive"
        REGEX = "regex"
        ROUND_ROBIN = "round_robin"
        RANDOM = "random"


class AntiFraudRateLimit:
    EMULATOR_CHECK = 'emulator_check'


class FeatureNameConst:
    ANTIFRAUD_STORE_MONNAI_LOG = 'antifraud_store_monnai_log'
