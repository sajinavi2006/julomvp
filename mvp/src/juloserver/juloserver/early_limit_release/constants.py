MINIMUM_USED_LIMIT = 100
DEFAULT_DELAY_SECONDS_CALL_FROM_REPAYMENT = 5 * 60


class EarlyReleaseCheckingType:
    EXPERIMENTATION = 'experimentation'
    PAID_ON_TIME = 'paid_on_time'
    PRE_REQUISITE = 'pre_requisite'
    REGULAR = 'regular'
    PGOOD = 'pgood'
    ODIN = 'odin'
    REPEAT = 'repeat'
    FDC = 'fdc'
    USED_LIMIT = 'used_limit'
    LOAN_DURATION = 'loan_duration'

    CHOICES = [
        (EXPERIMENTATION, 'Experimentation'),
        (PAID_ON_TIME, 'Paid on time'),
        (PRE_REQUISITE, 'Pre-requisite'),
        (REGULAR, 'Regular'),
        (PGOOD, 'Pgood'),
        (ODIN, 'Odin'),
        (REPEAT, 'Repeat'),
        (FDC, 'fdc'),
        (USED_LIMIT, 'Used limit'),
        (LOAN_DURATION, 'Loan duration'),
    ]


class PgoodRequirement:
    DEFAULT= 1
    TOP_LIMIT = 1
    BOTTOM_LIMIT = .0


class OdinRequirement:
    DEFAULT= 1
    TOP_LIMIT = 1
    BOTTOM_LIMIT = .0


class PgoodCustomerCheckReasons:
    PASSED_CHECK = "Passed pgood check"
    FAILED_LT = "Customer's pgood is less than criteria pgood"


class OdinCustomerCheckReasons:
    PASSED_CHECK = "Passed odin check"
    FAILED_NF = "Customer's odin is not found"
    FAILED_LT = "Customer's odin is less than criteria odin"


class RegularCustomerCheckReasons:
    FAILED_REGULAR_CHECK = 'Failed regular customer check'
    PASSED_REGULAR_CHECK = 'Passed regular customer check'


class RepeatCustomerCheckReasons:
    EMPTY_PAID_DATE = 'Customer has not paid once'
    INCORRECT_PRODUCT_LINE = 'Application product line code incorrect'
    FAILED_REPEAT_CHECK = 'Failed Repeat Check'
    PASSED_REPEAT_CHECK = 'Passed Repeat Check'


class UsedLimitCustomerCheckReasons:
    FAILED_USED_LIMIT_CHECK = 'Failed Used Limit Check'
    PASSED_USED_LIMIT_CHECK = 'Passed Used Limit Check'


class LoanDurationsCheckReasons:
    MISSING_EXPERIMENT_CONFIG = 'Missing experiment config'
    PASSED_LOAN_DURATION_PAYMENT_RULE = 'Passed loan duration payment rule'
    LOAN_DURATION_FAILED = 'Loan duration failed'
    MIN_PAYMENT_FAILED = 'Min payment failed'


class FeatureNameConst:
    EARLY_LIMIT_RELEASE = 'early_limit_release'
    EARLY_LIMIT_RELEASE_REPAYMENT_SIDE = 'early_limit_release_repayment_side'


class ExperimentationReasons:
    PASSED_EXPERIMENTATION_ALREADY_MAPPED = 'Passed, because experimentation already mapped before'
    PASSED_EXPERIMENTATION_FOUND_MAPPING = 'Passed, found experimentation for mapping'
    FAILED_EXPERIMENT_IS_DELETED = 'Experiment is deleted'
    FAILED_NO_EXPERIMENT_MATCHED = 'No experiment matched'


class ExperimentOption:
    OPTION_2 = 'OPTION_2'

    CHOICES = (
        (OPTION_2, 'OPTION 2'),
    )


class PreRequisiteCheckReasons:
    PASSED_PRE_REQUISITE_CHECK = 'Passed pre-requisite check'
    FAILED_PRE_REQUISITE_CHECK = 'Failed pre-requisite check'
    FAILED_CUSTOMER_HAS_LOAN_REFINANCING = 'customer has loan refinancing'
    NOT_FULLY_PAID_INSTALLMENT = 'not fully paid installment'


class FDCCustomerCheckReasons:
    FAILED_FDC_CHECK = 'Failed FDC Check'
    PASSED_FDC_CHECK = 'Passed FDC Check'


class PaidOnTimeReasons:
    FAILED_PAID_ON_TIME = 'Payment not paid on time'
    PASSED_PAID_ON_TIME = 'Payment paid on time'


class CreditModelResult:
    pgood = 0.8


class EarlyLimitReleaseMoengageStatus:
    SUCCESS = 'success'
    ROLLBACK = 'rollback'


class ReleaseTrackingType:
    EARLY_RELEASE = 'early_release'
    LAST_RELEASE = 'last_release'

    CHOICES = [
        (EARLY_RELEASE, 'Early release'),
        (LAST_RELEASE, 'Last release'),
    ]
