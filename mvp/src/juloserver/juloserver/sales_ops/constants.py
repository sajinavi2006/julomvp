
QUERY_LIMIT = 2000
PRIORITY_LINEUP_SIZE = 1000
PROMOTION_AGENT_OFFER_AVAILABLE_AT_LEAST_DAYS = 6


class ScoreCriteria:
    MONETARY = 'monetary'
    RECENCY = 'recency'

    @staticmethod
    def choices():
        return (
            (ScoreCriteria.RECENCY, ScoreCriteria.RECENCY.title()),
            (ScoreCriteria.MONETARY, ScoreCriteria.MONETARY.title()),
        )


class CustomerType:
    FTC = 'ftc'
    REPEAT_OS = 'repeat_os'
    REPEAT_NO_OS = 'repeat_no_os'

    @staticmethod
    def choices():
        return (
            (CustomerType.FTC, CustomerType.FTC.title()),
            (CustomerType.REPEAT_OS, CustomerType.REPEAT_OS.title()),
            (CustomerType.REPEAT_NO_OS, CustomerType.REPEAT_NO_OS.title()),
        )

    # priority left to right = greatest to lowest
    CUSTOMER_TYPE_PRIORITY = [FTC, REPEAT_OS, REPEAT_NO_OS]


class SalesOpsSettingConst:
    RECENCY_PERCENTAGES = 'recency_percentages'
    MONETARY_PERCENTAGES = 'monetary_percentages'
    LINEUP_MIN_AVAILABLE_LIMIT = 'lineup_min_available_limit'
    LINEUP_DELAY_PAID_COLLECTION_CALL_DAY = 'lineup_delay_paid_collection_call_day'
    AUTODIAL_RPC_ASSIGNMENT_DELAY_HOUR = 'autodial_rpc_assignment_delay_hour'
    AUTODIAL_END_CALL_HOUR = 'autodial_end_call_hour'
    LINEUP_MIN_AVAILABLE_DAYS = 'lineup_min_available_days'
    LINEUP_MAX_USED_LIMIT_PERCENTAGE = 'lineup_max_used_limit_percentage'
    LINEUP_LOAN_RESTRICTION_CALL_DAY = 'lineup_loan_restriction_call_day'
    LINEUP_DISBURSEMENT_RESTRICTION_CALL_DAY = 'lineup_disbursement_restriction_call_day'
    LINEUP_AND_AUTODIAL_NON_RPC_ATTEMPT_COUNT = 'lineup_and_autodial_non_rpc_attempt_count'
    LINEUP_AND_AUTODIAL_NON_RPC_DELAY_HOUR = 'lineup_and_autodial_non_rpc_delay_hour'
    LINEUP_AND_AUTODIAL_NON_RPC_FINAL_DELAY_HOUR = 'lineup_and_autodial_non_rpc_final_delay_hour'
    LINEUP_AND_AUTODIAL_RPC_DELAY_HOUR = 'lineup_and_autodial_rpc_delay_hour'
    BUCKET_RESET_DAY = 'bucket_reset_day'

    DEFAULT_RECENCY_PERCENTAGES = '20,20,20,20,20'
    DEFAULT_MONETARY_PERCENTAGES = '20,20,20,20,20'
    DEFAULT_LINEUP_MIN_AVAILABLE_LIMIT = 500000
    DEFAULT_LINEUP_DELAY_PAID_COLLECTION_CALL_DAY = 1
    DEFAULT_AUTODIAL_RPC_ASSIGNMENT_DELAY_HOUR = 168
    DEFAULT_AUTODIAL_END_CALL_HOUR = 18  # 18:00:00 WIB
    DEFAULT_LINEUP_MIN_AVAILABLE_DAYS = 30
    DEFAULT_LINEUP_MAX_USED_LIMIT_PERCENTAGE = 0.9
    DEFAULT_LINEUP_LOAN_RESTRICTION_CALL_DAY = 7
    DEFAULT_LINEUP_DISBURSEMENT_RESTRICTION_CALL_DAY = 14
    DEFAULT_LINEUP_AND_AUTODIAL_NON_RPC_ATTEMPT_COUNT = 2
    DEFAULT_LINEUP_AND_AUTODIAL_NON_RPC_DELAY_HOUR = 15
    DEFAULT_LINEUP_AND_AUTODIAL_NON_RPC_FINAL_DELAY_HOUR = 168
    DEFAULT_LINEUP_AND_AUTODIAL_RPC_DELAY_HOUR = 720
    DEFAULT_BUCKET_RESET_DAY = 1


class SalesOpsRoles:
    SALES_OPS = 'sales_ops'


class AutodialerConst:
    SUBJECT = 'SALES OPS'

    SESSION_START = 'session_started'
    SESSION_STOP = 'session_stop'
    SESSION_ACTION = 'session_action'

    SESSION_ACTION_SUCCESS = 'session_action_success'
    SESSION_ACTION_FAIL = 'session_action_fail'

    ACTION_UNKNOWN = 'Unknown Action'


class SalesOpsVendorName:
    IN_HOUSE = 'In-house'


class VendorRPCConst:
    FS_NAME = 'sales_ops_vendor_rpc_fs'
    DEFAULT_DATETIME_FORMAT = "%d-%m-%Y %H:%M:%S"
    VALID_CONTENT_TYPES_UPLOAD = [
        'text/csv',
        'application/vnd.ms-excel',
        'text/x-csv',
        'application/csv',
        'application/x-csv',
        'text/comma-separated-values',
        'text/x-comma-separated-values',
        'text/tab-separated-values'
    ]


class SalesOpsPDSConst:
    class PromoCode:
        FS_NAME = 'sales_ops_pds_promo_code'
        CATEGORY = 'sales_ops_pds'


class UploadSalesOpsVendorRPC:
    SUCCESS = 'success'
    LINEUP_DOES_NOT_EXISTED = 'sales ops lineup does not existed'
    VENDOR_AGENT_DOES_NOT_EXISTED = 'vendor agent does not existed'
    AGENT_DOES_NOT_EXISTED = 'agent does not existed'
    INVALID_FORMAT_COMPLETED_DATE = 'invalid format completed date'
    INVALID_COMPLETED_DATE = 'completed date < current date'


class BucketCode:
    GRADUATION = 'graduation'


class SalesOpsAlert:
    CHANNEL = '#sales_ops_alerts'
    SUCCESS_MESSAGE = '<!here> Today init sales ops lineup data is successful'
    FAILURE_MESSAGE = '<!here> Today init sales ops lineup data is failed. ' \
                      ' Please check!'


SALES_OPS_FILTER_FIELD_CHOICES_DEFAULT = [
    ('application_id', 'Application ID'),
    ('full_name', 'Full Name'),
    ('email', 'Email'),
    ('mobile_phone_1', 'Mobile Phone 1'),
    ('set_limit', 'Current Given Limit'),
    ('available_limit', 'Available Limit'),
    ('date_limit_approved', 'Date Limit Approved'),
    ('pgood', 'PGood'),
    ('fund_transfer_ts', 'Last Disbursement'),
]


SALES_OPS_FILTER_FIELD_CHOICES_BUCKET_MAP = {
    BucketCode.GRADUATION: [
        ('application_id', 'Application ID'),
        ('full_name', 'Full Name'),
        ('email', 'Email'),
        ('mobile_phone_1', 'Mobile Phone 1'),
        ('set_limit', 'Current Given Limit'),
        ('last_graduated_date', 'Last Graduated Date'),
        ('available_limit', 'Available Limit'),
        ('fund_transfer_ts', 'Last Disbursement'),
    ]
}

SEARCH_FILTER_MAPPINGS = {
    'application_id': 'latest_application__id',
    'full_name': 'latest_application__fullname',
    'email': 'latest_application__email',
    'mobile_phone_1': 'latest_application__mobile_phone_1',
    'set_limit': 'latest_account_limit__set_limit',
    'available_limit': 'latest_account_limit__available_limit',
    'date_limit_approved': 'latest_account_limit__cdate__date',
    'pgood': 'latest_account_property__pgood',
    'fund_transfer_ts': 'latest_disbursed_loan__fund_transfer_ts__date',
    'last_graduated_date': 'account__graduation_accounts__cdate__date',
}


EXTRA_FILTER_MAPPINGS = {
    'last_graduated_date': {
        'account__graduation_accounts__latest_flag': True
    }
}
