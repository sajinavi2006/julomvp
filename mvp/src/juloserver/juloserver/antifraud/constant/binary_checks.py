from enum import Enum


class StatusEnum(Enum):
    UNKNOWN = "unknown"
    ERROR = "error"
    RETRYING = "retrying"  # not supported yet
    BYPASSED_HOLDOUT = "bypassed_holdout"
    DO_NOTHING = "do_nothing"
    MOVE_APPLICATION_TO115 = "move_application_to115"
    MOVE_APPLICATION_TO133 = "move_application_to133"
    MOVE_APPLICATION_TO135 = "move_application_to135"
    TELCO_MAID_LOCATION = "telco_maid_location"
    FRAUD_REPORTED_LOAN = "fraud_reported_loan"
    SWIFT_LIMIT_DRAINER = "swift_limit_drainer"

    @classmethod
    def _missing_(self, val):
        return self.UNKNOWN

    @property
    def is_loan_block(self):
        return self in [
            self.SWIFT_LIMIT_DRAINER,
            self.FRAUD_REPORTED_LOAN,
            self.TELCO_MAID_LOCATION,
        ]


class BinaryCheckType (object):
    APPLICATION = "application"
    LOAN = "loan"
