from collections import namedtuple
from enum import Enum


INDONESIA = 'Indonesia'
DANA_BANK_NAME = "DANA_PARTNER"
DANA_PREFIX_IDENTIFIER = 999
DANA_SUFFIX_EMAIL = '+dana@julopartner.com'
DANA_CASH_LOAN_SUFFIX_EMAIL = '+danacashloan@julopartner.com'
DANA_PAYMENT_METHOD_NAME = 'DANA_MANUAL_USER'
DANA_PAYMENT_METHOD_CODE = '0003'
DANA_ACCOUNT_LOOKUP_NAME = 'DANA'
BILL_STATUS_PAID_OFF = "PAID"
MAX_LATE_FEE_APPLIED = 120
ENCRYPT_BLOCK_SIZE = 16
BILL_STATUS_PARTIAL = "INIT"
DANA_DEFAULT_TNC_AND_PRIVACY_POLICY_URL = (
    "https://a.m.dana.id/resource/htmls/dana-credit/DANA-cicil-tnc.html"
)
BILL_STATUS_CANCEL = "CANCEL"
DANA_HEADER_X_PARTNER_ID = "JULO"
DANA_HEADER_CHANNEL_ID = "JULO"
MAP_PAYMENT_FREQUENCY_TO_UNIT = {
    'daily': 'day',
    'weekly': 'week',
    'biweekly': 'biweek',
    'monthly': 'month',
}


class DanaErrorMessage:
    SUCCESSFUL = 'Successful'
    REQUEST_IN_PROGRESS = 'Request In Progress'
    BAD_REQUEST = 'Bad Request'
    INVALID_FIELD_FORMAT = 'Invalid Field Format'
    INVALID_MANDATORY_FIELD = 'Invalid Mandatory Field'
    INVALID_SIGNATURE = 'Unauthorized. Invalid Signature'
    INCONSISTENT_REQUEST = 'Inconsistent Request'
    GENERAL_ERROR = 'General Error'
    INTERNAL_SERVER_ERROR = 'Internal Server Error'
    DOCUMENT_NOT_FOUND = 'Document is in progress, Please try again in a few minutes'
    INVALID_ENCRYPTED_LOAN_XID = 'enc lxid tidak ditemukan'
    INVALID_LOAN_XID = 'lxid tidak ditemukan'
    INVALID_REFERENCE_ID = 'reference id tidak ditemukan'
    AGREEMENT_IN_PROCESS = 'Perjanjian pendanaan sedang di proses, silakan coba lagi nanti'
    DO_NOT_HONOR = 'Do Not Honor'
    INVALID_UPDATE_KEY = 'Unauthorized. Invalid Update Key'


class BindingResponseCode:
    BindingResponse = namedtuple('ERROR_KEY', ['code', 'message'])

    SUCCESS = BindingResponse("2000600", DanaErrorMessage.SUCCESSFUL)
    ACCEPTED = BindingResponse("2020600", DanaErrorMessage.REQUEST_IN_PROGRESS)
    BAD_REQUEST = BindingResponse("4000600", DanaErrorMessage.BAD_REQUEST)
    INVALID_FIELD_FORMAT = BindingResponse("4000601", DanaErrorMessage.INVALID_FIELD_FORMAT)
    INVALID_MANDATORY_FIELD = BindingResponse("4000602", DanaErrorMessage.INVALID_MANDATORY_FIELD)
    INVALID_SIGNATURE = BindingResponse("4010600", DanaErrorMessage.INVALID_SIGNATURE)
    INCONSISTENT_REQUEST = BindingResponse("4040618", DanaErrorMessage.INCONSISTENT_REQUEST)
    GENERAL_ERROR = BindingResponse("5000600", DanaErrorMessage.GENERAL_ERROR)


class BindingRejectCode:
    error_tuple_data = namedtuple('ERROR_KEY', ['code', 'reason'])

    EXISTING_CUSTOMER_INVALID_PHONE = error_tuple_data(
        'EXISTING_CUSTOMER_INVALID_PHONE', 'Phone number does not match with NIK existing data'
    )
    EXISTING_USER_INVALID_NIK = error_tuple_data(
        'EXISTING_USER_INVALID_NIK', 'NIK number does not match with phone existing data'
    )
    BLACKLISTED_CUSTOMER = error_tuple_data(
        'BLACKLISTED_CUSTOMER', 'Invalid user, user is blacklisted'
    )
    FRAUD_CUSTOMER = error_tuple_data('FRAUD_CUSTOMER', 'Invalid user, fraud user')
    DELINQUENT_CUSTOMER = error_tuple_data(
        'DELINQUENT_CUSTOMER',
        'Invalid user, user is delinquent',
    )
    EXISTING_USER_DIFFERENT_CUSTOMER_ID = error_tuple_data(
        'EXISTING_USER_DIFFERENT_CUSTOMER_ID',
        'User Existing but different customerID',
    )
    USER_HAS_REGISTERED = error_tuple_data(
        'USER_HAS_REGISTERED',
        'User is already registered',
    )
    HAS_INCONSISTENT_REQUEST = error_tuple_data(
        'HAS_INCONSISTENT_REQUEST',
        'Has inconsistent data from data that has been sent',
    )
    HAS_INVALID_FIELD_FORMAT = error_tuple_data(
        'HAS_INVALID_FIELD_FORMAT',
        'Has several invalid formats from data that has been sent',
    )
    HAS_INVALID_MANDATORY_FIELD = error_tuple_data(
        'HAS_INVALID_MANDATORY_FIELD',
        'Has several invalid mandatory fields from data that has been sent',
    )
    INTERNAL_SERVER_ERROR = error_tuple_data(
        'INTERNAL_SERVER_ERROR',
        'Internal Server Error please try again later',
    )
    WHITELISTED_FRAUD_USER = error_tuple_data(
        'WHITELISTED_FRAUD_USER',
        'Whitelisted fraud User',
    )
    WHITELISTED_EXISTING_USER_INVALID_NIK = error_tuple_data(
        'WHITELISTED_EXISTING_USER_INVALID_NIK',
        'Whitelisted existing user invalid NIK',
    )
    WHITELISTED_DELINQUENT_USER = error_tuple_data(
        'WHITELISTED_DELINQUENT_USER',
        'Whitelisted delinquent user',
    )
    WHITELISTED_BLACKLIST_USER = error_tuple_data(
        'WHITELISTED_BLACKLIST_USER',
        'Whitelisted blacklist user',
    )
    UNDERAGED_CUSTOMER = error_tuple_data(
        'UNDERAGED_CUSTOMER',
        'Invalid user, user is under 21',
    )
    EXISTING_USER_DIFFERENT_NIK = error_tuple_data(
        'EXISTING_USER_DIFFERENT_NIK', 'User Existing but different NIK'
    )
    NON_EXISTING_DANA_CICIL_USER = error_tuple_data(
        'NON_EXISTING_DANA_CICIL_USER',
        'not existing dana cicil user',
    )


class PaymentResponseCodeMessage:
    PaymentResponse = namedtuple('PaymentResponse', ['code', 'message'])

    SUCCESS = PaymentResponse("2005600", DanaErrorMessage.SUCCESSFUL)
    ACCEPTED = PaymentResponse("2025600", DanaErrorMessage.REQUEST_IN_PROGRESS)
    BAD_REQUEST = PaymentResponse("4005600", DanaErrorMessage.BAD_REQUEST)
    INVALID_FIELD_FORMAT = PaymentResponse("4005601", DanaErrorMessage.INVALID_FIELD_FORMAT)
    INVALID_MANDATORY_FIELD = PaymentResponse("4005602", DanaErrorMessage.INVALID_MANDATORY_FIELD)
    INVALID_SIGNATURE = PaymentResponse("4015600", DanaErrorMessage.INVALID_SIGNATURE)
    INCONSISTENT_REQUEST = PaymentResponse("4045618", DanaErrorMessage.INCONSISTENT_REQUEST)
    GENERAL_ERROR = PaymentResponse("5005600", DanaErrorMessage.GENERAL_ERROR)
    INTERNAL_SERVER_ERROR = PaymentResponse("5005601", DanaErrorMessage.INTERNAL_SERVER_ERROR)


class DanaLoanDuration:
    FOUR = 4


class RepaymentResponseCodeMessage:
    RepaymentResponse = namedtuple('RepaymentResponse', ['code', 'message'])

    SUCCESS = RepaymentResponse("2000000", DanaErrorMessage.SUCCESSFUL)
    BAD_REQUEST = RepaymentResponse("4000000", DanaErrorMessage.BAD_REQUEST)
    INVALID_FIELD_FORMAT = RepaymentResponse("4000001", DanaErrorMessage.INVALID_FIELD_FORMAT)
    INVALID_MANDATORY_FIELD = RepaymentResponse("4000002", DanaErrorMessage.INVALID_MANDATORY_FIELD)
    INVALID_SIGNATURE = RepaymentResponse("4010000", DanaErrorMessage.INVALID_SIGNATURE)
    INCONSISTENT_REQUEST = RepaymentResponse("4040018", DanaErrorMessage.INCONSISTENT_REQUEST)
    GENERAL_ERROR = RepaymentResponse("5000000", DanaErrorMessage.GENERAL_ERROR)
    INTERNAL_SERVER_ERROR = RepaymentResponse("5000001", DanaErrorMessage.INTERNAL_SERVER_ERROR)


class LoanStatusResponseCodeMessage:
    LoanStatusResponse = namedtuple('LoanStatusResponse', ['code', 'message'])

    SUCCESS = LoanStatusResponse("2005500", DanaErrorMessage.SUCCESSFUL)
    BAD_REQUEST = LoanStatusResponse("4005500", DanaErrorMessage.BAD_REQUEST)
    INVALID_FIELD_FORMAT = LoanStatusResponse("4005501", DanaErrorMessage.INVALID_FIELD_FORMAT)
    INVALID_MANDATORY_FIELD = LoanStatusResponse(
        "4005502", DanaErrorMessage.INVALID_MANDATORY_FIELD
    )
    INVALID_SIGNATURE = LoanStatusResponse("4015500", DanaErrorMessage.INVALID_SIGNATURE)
    INCONSISTENT_REQUEST = LoanStatusResponse("4045518", DanaErrorMessage.INCONSISTENT_REQUEST)
    GENERAL_ERROR = LoanStatusResponse("5005500", DanaErrorMessage.GENERAL_ERROR)
    INTERNAL_SERVER_ERROR = LoanStatusResponse("5005501", DanaErrorMessage.INTERNAL_SERVER_ERROR)


class DanaBasePath:
    onboarding = 'onboarding'
    loan = 'loan'
    repayment = 'repayment'
    collection = 'collection'
    loan_status = 'loan_status'
    refund = 'refund'
    account = 'account'
    account_inquiry = 'account_inquiry'
    account_info = 'account_info'


class ErrorType:
    BAD_REQUEST = 'bad_request'
    GENERAL_ERROR = 'general_error'
    INVALID_FIELD_FORMAT = 'invalid_field_format'
    INVALID_SIGNATURE = 'invalid_signature'
    INVALID_MANDATORY_FIELD = 'invalid_mandatory_field'


class ErrorDetail:
    NULL = 'This field may not be null.'
    BLANK = 'This field may not be blank.'
    REQUIRED = 'This field is required.'
    BLANK_LIST = 'This list may not be empty.'
    MAX_CHARACTER = 'Ensure this field has no more than'
    EXPECTED_DICT = 'Expected a dictionary of items but got type'
    EXPECTED_LIST = 'Expected a list of items but got type'
    INVALID_DATE_FORMAT = 'Datetime has wrong format'
    INVALID_BOOLEAN = 'is not a valid boolean'

    @classmethod
    def invalid_format(cls):
        return {cls.MAX_CHARACTER, cls.EXPECTED_DICT, cls.EXPECTED_LIST, cls.INVALID_DATE_FORMAT}


class RedisKey(object):
    DANA_DIALER_ACCOUNT_PAYMENTS = 'dana:dialer_account_payments'
    POPULATE_ELIGIBLE_CALL_DANA_ACCOUNT_PAYMENT_IDS = (
        'populate_eligible_call_dana_account_payment_ids_{}_part_{}'
    )
    EXCLUDED_DANA_BY_ACCOUNT_STATUS = 'excluded_dana_by_account_status_{}|part_{}'
    EXCLUDED_KEY_LIST_DANA_ACCOUNT_IDS_PER_BUCKET = 'list_excluded_dana_account_ids_key_{}|part_{}'
    CLEAN_DANA_ACCOUNT_PAYMENT_IDS_FOR_DIALER_RELATED = (
        'clean_dana_account_payment_ids_for_dialer_related_{}|part_{}'
    )
    CONSTRUCTED_DANA_DATA_FOR_SEND_TO_INTELIX = 'constructed_dana_data_for_send_to_intelix_{}|{}'
    CONSTRUCTED_DANA_DATA_FOR_SEND_TO_AIRUDDER = 'constructed_dana_data_for_send_to_airudder_{}|{}'
    CHECKING_DATA_GENERATION_STATUS = 'CHECKING_DATA_GENERATION_STATUS_{}'
    DAILY_TASK_ID_FROM_DIALER = 'daily_task_id_from_dialer'


class RejectCodeMessage:
    RejectCodeReason = namedtuple('RejectCodeReason', ['code', 'message'])

    IDEMPOTENCY = RejectCodeReason('IDEMPOTENCY_REQUEST', 'partnerReferenceNo: {} has been proceed')


class FeatureNameConst(object):
    DANA_BLOCK_INTELIX_TRAFFIC = 'dana_block_intelix_traffic'
    DANA_BLOCK_AIRUDDER_TRAFFIC = 'dana_block_ai_rudder_traffic'
    AI_RUDDER_GROUP_NAME_CONFIG = 'ai_rudder_group_name_config'
    AI_RUDDER_TASKS_STRATEGY_CONFIG = 'ai_rudder_tasks_strategy_config'
    DANA_AI_RUDDER_TASKS_STRATEGY_CONFIG = 'dana_ai_rudder_tasks_strategy_config'
    DANA_AI_RUDDER_CUT_OFF_DATE = 'dana_ai_rudder_cut_off_date'


class DanaDefaultBatchingCons(object):
    DANA_B_ALL_DEFAULT_BATCH = 5000


class DanaDocumentConstant:
    LOAN_AGREEMENT_TYPE = "dana_loan_agreement"
    DOCUMENT_SERVICE = "oss"
    EXPIRY_TIME = 60


class DanaHashidsConstant:
    MIN_LENGTH = 16


class DanaUploadAsyncStateType(object):
    DANA_REPAYMENT_SETTLEMENT = "DANA_REPAYMENT_SETTLEMENT"
    DANA_REFUND_REPAYMENT_SETTLEMENT = "DANA_REFUND_REPAYMENT_SETTLEMENT"
    DANA_REFUND_PAYMENT_SETTLEMENT = "DANA_REFUND_PAYMENT_SETTLEMENT"
    DANA_PAYMENT_SETTTLEMENT = "DANA_PAYMENT_SETTTLEMENT"
    DANA_UPDATE_FUND_TRANSFER_TS = "DANA_UPDATE_FUND_TRANSFER_TS"
    DANA_LENDER_PAYMENT_UPLOAD = "DANA_LENDER_PAYMENT_UPLOAD"


DANA_REPAYMENT_SETTLEMENT_HEADERS = [
    "is_inserted",
    "is_valid",
    "partnerId",
    "lenderProductId",
    "partnerReferenceNo",
    "billId",
    "billStatus",
    "principalAmount",
    "interestFeeAmount",
    "lateFeeAmount",
    "totalAmount",
    "transTime",
    "waivedPrincipalAmount",
    "waivedInterestFeeAmount",
    "waivedLateFeeAmount",
    "totalWaivedAmount",
    "error",
    "action",
    "note",
]

DANA_SERVICE_FEE_RATE_P3 = [68.75, 76.56, 84.38, 92.19]


class RepaymentRejectCode:
    error_tuple_data = namedtuple('ERROR_KEY', ['code', 'reason'])

    All_BILL_ID_HAS_LOAN_CANCELED = error_tuple_data(
        'All_BILL_ID_HAS_LOAN_CANCELED', 'All bill has loan canceled'
    )
    HAS_BILL_ID_WITH_LOAN_CANCELED = error_tuple_data(
        'HAS_BILL_ID_WITH_LOAN_CANCELED',
        'Partially success but have invalid loan id because loan is canceled',
    )


class RepaymentReferenceStatus:
    SUCCESS = "success"
    PENDING = "pending"
    CANCELLED = "cancelled"
    FAILED = "failed"


class OnboardingRejectReason:
    BLACKLISTED = 'blacklist_customer_check'
    FRAUD = 'Other_fraud_suspicions'
    DELINQUENT = 'prev_delinquency_check'
    EXISTING_PHONE_DIFFERENT_NIK = 'Phone number does not match with existing data'
    UNDERAGE = 'Age under 21'


class OnboardingApproveReason:
    '''
    BYPASS_PHONE_SAME_NIK_NEW_RULES and APPROVED_WITH_NEW_NIK_RULES
    This rules basically to doing skip if phone_number from DANA
    Is existed on JULO but have different NIK.
    On this flag, we need to check if the ops.customer registration creation (cdate)
    Lower than config threshold ideally 365 days (1 year)
    We need to check and reject it, Greater than 365 days
    We can continue the process but need to track with flag
    Detail on card: PARTNER-4492
    '''

    # Flagging for user that passed on phone check,
    # still have a chance rejected to another validation (Fraud, blacklist, etc)
    # Flag will saved into ops.partnership_application_flag column name
    BYPASS_PHONE_SAME_NIK_NEW_RULES = "bypass_phone_with_same_NIK_new_rules"

    # Flagging for user success to 190 but with a this notes
    # Flag will saved into ops.application_history column change_reason at change to x190
    APPROVED_WITH_NEW_NIK_RULES = "user_approved_with_new_NIK_rules"


class PaymentReferenceStatus:
    SUCCESS = "success"
    PENDING = "pending"
    CANCELLED = "cancelled"
    FAILED = "failed"


class DanaTransactionStatusCode:
    TransactionStatus = namedtuple('TransactionStatus', ['code', 'desc'])

    SUCCESS = TransactionStatus("00", "Success")
    INITIATED = TransactionStatus("01", "Initiated")
    PENDING = TransactionStatus("03", "Pending")
    CANCELED = TransactionStatus("05", "Canceled")
    FAILED = TransactionStatus("06", "Failed")
    NOT_FOUND = TransactionStatus("07", "Not found")


class PaymentConsultErrorStatus(object):
    PAYMENT_CONSULT_EXPIRED = "PAYMENT_CONSULT_EXPIRED"
    PAYMENT_CONSULT_LENDER_BAD_REQUEST = "PAYMENT_CONSULT_LENDER_BAD_REQUEST"
    PAYMENT_CONSULT_LENDER_INVALID_FIELD_FORMAT = "PAYMENT_CONSULT_LENDER_INVALID_FIELD_FORMAT"
    PAYMENT_CONSULT_LENDER_INVALID_MANDATORY_FIELD = (
        "PAYMENT_CONSULT_LENDER_INVALID_MANDATORY_FIELD"
    )
    PAYMENT_CONSULT_LENDER_UNAUTHORIZED = "PAYMENT_CONSULT_LENDER_UNAUTHORIZED"
    PAYMENT_CONSULT_LENDER_INCONSISTENT_REQUEST = "PAYMENT_CONSULT_LENDER_INCONSISTENT_REQUEST"
    PAYMENT_CONSULT_LENDER_GENERAL_ERROR = "PAYMENT_CONSULT_LENDER_GENERAL_ERROR"
    PAYMENT_CONSULT_LENDER_INTERNAL_SERVER_ERROR = "PAYMENT_CONSULT_LENDER_INTERNAL_SERVER_ERROR"
    PAYMENT_CONSULT_LENDER_UNKNOWN_ERROR = "PAYMENT_CONSULT_LENDER_UNKNOWN_ERROR"
    PAYMENT_CONSULT_QUERY_LENDER_STATUS_INVALID = "PAYMENT_CONSULT_QUERY_LENDER_STATUS_INVALID"
    PAYMENT_CONSULT_QUERY_LENDER_UNKNOWN_ERROR = "PAYMENT_CONSULT_QUERY_LENDER_UNKNOWN_ERROR"
    PAYMENT_CONSULT_QUERY_LENDER_BAD_REQUEST = "PAYMENT_CONSULT_QUERY_LENDER_BAD_REQUEST"
    PAYMENT_CONSULT_QUERY_LENDER_INVALID_FIELD_FORMAT = (
        "PAYMENT_CONSULT_QUERY_LENDER_INVALID_FIELD_FORMAT"
    )
    PAYMENT_CONSULT_QUERY_LENDER_INVALID_MANDATORY_FIELD = (
        "PAYMENT_CONSULT_QUERY_LENDER_INVALID_MANDATORY_FIELD"
    )
    PAYMENT_CONSULT_QUERY_LENDER_UNAUTHORIZED = "PAYMENT_CONSULT_QUERY_LENDER_UNAUTHORIZED"
    PAYMENT_CONSULT_QUERY_LENDER_GENERAL_ERROR = "PAYMENT_CONSULT_QUERY_LENDER_GENERAL_ERROR"
    PAYMENT_CONSULT_QUERY_LENDER_INTERNAL_SERVER_ERROR = (
        "PAYMENT_CONSULT_QUERY_LENDER_INTERNAL_SERVER_ERROR"
    )
    PAYMENT_CONSULT_PROCESS_ERROR = "PAYMENT_CONSULT_PROCESS_ERROR"
    LIMIT_EXCEEDED = "LIMIT_EXCEEDED"
    DISBURSEMENT_PARTNER_BAD_REQUEST = "DISBURSEMENT_PARTNER_BAD_REQUEST"
    DISBURSEMENT_PARTNER_INVALID_FIELD_FORMAT = "DISBURSEMENT_PARTNER_INVALID_FIELD_FORMAT"
    DISBURSEMENT_PARTNER_INVALID_MANDATORY_FIELD = "DISBURSEMENT_PARTNER_INVALID_MANDATORY_FIELD"
    DISBURSEMENT_PARTNER_UNAUTHORIZED = "DISBURSEMENT_PARTNER_UNAUTHORIZED"
    DISBURSEMENT_PARTNER_INVALID_TOKEN = "DISBURSEMENT_PARTNER_INVALID_TOKEN"
    DISBURSEMENT_PARTNER_CUSTOMER_TOKEN_NOT_FOUND = "DISBURSEMENT_PARTNER_CUSTOMER_TOKEN_NOT_FOUND"
    DISBURSEMENT_PARTNER_EXCEEDS_TRASACTION_AMOUNT_LIMIT = (
        "DISBURSEMENT_PARTNER_EXCEEDS_TRASACTION_AMOUNT_LIMIT"
    )
    DISBURSEMENT_PARTNER_SUSPECTED_FRAUD = "DISBURSEMENT_PARTNER_SUSPECTED_FRAUD"
    DISBURSEMENT_PARTNER_DO_NOT_HONOR = "DISBURSEMENT_PARTNER_DO_NOT_HONOR"
    DISBURSEMENT_PARTNER_GENERAL_ERROR = "DISBURSEMENT_PARTNER_GENERAL_ERROR"
    DISBURSEMENT_PARTNER_INVALID_CUSTOMER_TOKEN = "DISBURSEMENT_PARTNER_INVALID_CUSTOMER_TOKEN"
    DISBURSEMENT_PARTNER_UNKNOWN_ERROR = "DISBURSEMENT_PARTNER_UNKNOWN_ERROR"
    DISBURSEMENT_UNKNOWN_ERROR = "DISBURSEMENT_UNKNOWN_ERROR"
    DISBURSEMENT_INVALID_STATUS = "DISBURSEMENT_INVALID_STATUS"

    @property
    def is_need_to_cancel(self):
        return {
            self.PAYMENT_CONSULT_EXPIRED,
            self.PAYMENT_CONSULT_QUERY_LENDER_UNKNOWN_ERROR,
            self.PAYMENT_CONSULT_LENDER_UNKNOWN_ERROR,
            self.PAYMENT_CONSULT_QUERY_LENDER_STATUS_INVALID,
            self.PAYMENT_CONSULT_LENDER_GENERAL_ERROR,
            self.PAYMENT_CONSULT_LENDER_INTERNAL_SERVER_ERROR,
            self.PAYMENT_CONSULT_QUERY_LENDER_GENERAL_ERROR,
            self.PAYMENT_CONSULT_QUERY_LENDER_INTERNAL_SERVER_ERROR,
            self.PAYMENT_CONSULT_QUERY_LENDER_BAD_REQUEST,
            self.PAYMENT_CONSULT_QUERY_LENDER_INVALID_FIELD_FORMAT,
            self.PAYMENT_CONSULT_QUERY_LENDER_INVALID_MANDATORY_FIELD,
            self.PAYMENT_CONSULT_QUERY_LENDER_UNAUTHORIZED,
            self.PAYMENT_CONSULT_PROCESS_ERROR,
            self.LIMIT_EXCEEDED,
            self.DISBURSEMENT_PARTNER_BAD_REQUEST,
            self.DISBURSEMENT_PARTNER_INVALID_FIELD_FORMAT,
            self.DISBURSEMENT_PARTNER_INVALID_MANDATORY_FIELD,
            self.DISBURSEMENT_PARTNER_UNAUTHORIZED,
            self.DISBURSEMENT_PARTNER_INVALID_TOKEN,
            self.DISBURSEMENT_PARTNER_CUSTOMER_TOKEN_NOT_FOUND,
            self.DISBURSEMENT_PARTNER_EXCEEDS_TRASACTION_AMOUNT_LIMIT,
            self.DISBURSEMENT_PARTNER_SUSPECTED_FRAUD,
            self.DISBURSEMENT_PARTNER_DO_NOT_HONOR,
            self.DISBURSEMENT_PARTNER_GENERAL_ERROR,
            self.DISBURSEMENT_PARTNER_INVALID_CUSTOMER_TOKEN,
            self.DISBURSEMENT_PARTNER_UNKNOWN_ERROR,
            self.DISBURSEMENT_UNKNOWN_ERROR,
            self.DISBURSEMENT_INVALID_STATUS,
        }


class DanaMaritalStatusConst(object):
    MENIKAH = "Menikah"
    LAJANG = "Lajang"
    CERAI = "Cerai"
    JANDA_DUDA = "Janda / duda"


class RefundResponseCodeMessage:
    RefundResponse = namedtuple('RefundResponse', ['code', 'message'])

    SUCCESS = RefundResponse("2005800", DanaErrorMessage.SUCCESSFUL)
    BAD_REQUEST = RefundResponse("4005800", DanaErrorMessage.BAD_REQUEST)
    INVALID_FIELD_FORMAT = RefundResponse("4005801", DanaErrorMessage.INVALID_FIELD_FORMAT)
    INVALID_MANDATORY_FIELD = RefundResponse("4005802", DanaErrorMessage.INVALID_MANDATORY_FIELD)
    INVALID_SIGNATURE = RefundResponse("4015800", DanaErrorMessage.INVALID_SIGNATURE)
    INCONSISTENT_REQUEST = RefundResponse("4045818", DanaErrorMessage.INCONSISTENT_REQUEST)
    GENERAL_ERROR = RefundResponse("5005800", DanaErrorMessage.GENERAL_ERROR)
    INTERNAL_SERVER_ERROR = RefundResponse("5005801", DanaErrorMessage.INTERNAL_SERVER_ERROR)
    DO_NOT_HONOR = RefundResponse("4035805", DanaErrorMessage.DO_NOT_HONOR)


class DanaReferenceStatus:
    SUCCESS = "success"
    PENDING = "pending"
    CANCELLED = "cancelled"
    FAILED = "failed"


class DanaRefundErrorMessage:
    BLANK_FIELD = "Field may not be blank"
    REQUIRED_FIELD = "This field is required"
    MAX_CHAR = "Value is too long"
    NOT_NUMBER = "Value is not a number"
    INVALID_FORMAT = "Invalid format value"


class XIDGenerationMethod(Enum):
    UNIX_TIME = 1
    DATETIME = 2
    PRODUCT_LINE = 3


class DanaFDCResultStatus:
    INIT = 'init'
    APPROVE1 = 'Approve1'
    APPROVE2 = 'Approve2'
    APPROVE3 = 'Approve3'
    APPROVE4 = 'Approve4'
    APPROVE5 = 'Approve5'
    APPROVE6 = 'Approve6'
    ADDITIONAL_INFO = {
        APPROVE1: 'Write-Off',
        APPROVE2: 'Current Deliquent',
        APPROVE3: 'Deliquent 1 Year',
        APPROVE4: 'Deliquent 2 Year',
        APPROVE5: 'Non Deliquent',
        APPROVE6: 'No FDC Result',
    }
    FDC_STATUS_CHOICES = (
        (INIT, 'init'),
        (APPROVE1, 'Approve1'),
        (APPROVE2, 'Approve2'),
        (APPROVE3, 'Approve3'),
        (APPROVE4, 'Approve4'),
        (APPROVE5, 'Approve5'),
        (APPROVE6, 'Approve6'),
    )


class DanaFDCStatusSentRequest:
    PENDING = 'pending'
    FAIL = 'fail'
    CANCEL = 'cancel'
    SUCCESS = 'success'
    PROCESS = 'process'
    SUSPENDED = 'suspended'
    CHOICES = (
        (PENDING, 'pending'),
        (FAIL, 'fail'),
        (CANCEL, 'cancel'),
        (SUCCESS, 'success'),
        (SUSPENDED, 'suspended'),
    )


class DanaEndpointAPI(object):
    UPDATE_ACCOUNT_INFO = "/v1.0/user/update/account-info"


class AccountUpdateResponseCode:
    AccountUpdateResponse = namedtuple('ERROR_KEY', ['code', 'message'])

    SUCCESS = AccountUpdateResponse("2000000", DanaErrorMessage.SUCCESSFUL)
    BAD_REQUEST = AccountUpdateResponse("4000000", DanaErrorMessage.BAD_REQUEST)
    INVALID_FIELD_FORMAT = AccountUpdateResponse("4000001", DanaErrorMessage.INVALID_FIELD_FORMAT)
    INVALID_MANDATORY_FIELD = AccountUpdateResponse(
        "4000002", DanaErrorMessage.INVALID_MANDATORY_FIELD
    )
    INVALID_SIGNATURE = AccountUpdateResponse("4010000", DanaErrorMessage.INVALID_SIGNATURE)
    INVALID_UPDATE_KEY = AccountUpdateResponse("4010001", DanaErrorMessage.INVALID_UPDATE_KEY)
    GENERAL_ERROR = AccountUpdateResponse("5000000", DanaErrorMessage.GENERAL_ERROR)
    INTERNAL_SERVER_ERROR = AccountUpdateResponse("5000001", DanaErrorMessage.INTERNAL_SERVER_ERROR)


class AccountInfoResponseCode:
    AccountInfoResponse = namedtuple('ERROR_KEY', ['code', 'message'])

    SUCCESS = AccountInfoResponse("2000000", DanaErrorMessage.SUCCESSFUL)
    BAD_REQUEST = AccountInfoResponse("4000000", DanaErrorMessage.BAD_REQUEST)
    INVALID_FIELD_FORMAT = AccountInfoResponse("4000001", DanaErrorMessage.INVALID_FIELD_FORMAT)
    INVALID_MANDATORY_FIELD = AccountInfoResponse(
        "4000002", DanaErrorMessage.INVALID_MANDATORY_FIELD
    )
    INVALID_SIGNATURE = AccountInfoResponse("4010000", DanaErrorMessage.INVALID_SIGNATURE)
    INVALID_UPDATE_KEY = AccountInfoResponse("4010001", DanaErrorMessage.INVALID_UPDATE_KEY)
    GENERAL_ERROR = AccountInfoResponse("5000000", DanaErrorMessage.GENERAL_ERROR)
    INTERNAL_SERVER_ERROR = AccountInfoResponse("5000001", DanaErrorMessage.INTERNAL_SERVER_ERROR)


UPDATE_KEY_LIMIT = "limit"
UPDATE_KEY_FDC = "FDCFlag"
UPDATE_KEY_SELFIE = "selfieImage"
UPDATE_KEY_IDENTITY_CARD = "identityCardImage"

CUSTOMER_UPDATE_KEY = [
    UPDATE_KEY_FDC,
    UPDATE_KEY_LIMIT,
    UPDATE_KEY_SELFIE,
    UPDATE_KEY_IDENTITY_CARD,
]


class DanaAccountInfoStatus:
    PENDING = 'pending'
    FAIL = 'fail'
    CANCEL = 'cancel'
    SUCCESS = 'success'
    PROCESS = 'process'
    CHOICES = (
        (PENDING, 'pending'),
        (FAIL, 'fail'),
        (CANCEL, 'cancel'),
        (SUCCESS, 'success'),
    )


class DanaProductType(object):
    CICIL = 'LP00001'
    CASH_LOAN = 'CASH_LOAN_JULO_01'


DANA_ONBOARDING_FIELD_TO_TRACK = [
    'nik',
    'mobile_number',
    'proposed_credit_limit',
    'dob',
    'credit_score',
    'dana_customer_identifier',
    'registration_time',
    'full_name',
    'income',
]


class DanaBucket:
    DANA_BUCKET_AIRUDDER = "DANA_BUCKET_AIRUDDER"
    DANA_BUCKET_PEPPER = "DANA_BUCKET_PEPPER"
    DANA_BUCKET_PEPPER_91_PLUS = "DANA_BUCKET_PEPPER_91_PLUS"
    DANA_BUCKET_SIM = "DANA_BUCKET_SIM"


class DanaProduct:
    CICIL = "CICIL"
    CASHLOAN = "CASHLOAN"
    CICIL_CASHLOAN = "CICIL and CASHLOAN"


class AccountInquiryResponseCode:
    AccountInquiryResponse = namedtuple('ERROR_KEY', ['code', 'message'])

    SUCCESS = AccountInquiryResponse("2000800", DanaErrorMessage.SUCCESSFUL)
    ACCEPTED = AccountInquiryResponse("2020800", DanaErrorMessage.REQUEST_IN_PROGRESS)
    BAD_REQUEST = AccountInquiryResponse("4000800", DanaErrorMessage.BAD_REQUEST)
    INVALID_FIELD_FORMAT = AccountInquiryResponse("4000801", DanaErrorMessage.INVALID_FIELD_FORMAT)
    INVALID_MANDATORY_FIELD = AccountInquiryResponse(
        "4000802", DanaErrorMessage.INVALID_MANDATORY_FIELD
    )
    INVALID_SIGNATURE = AccountInquiryResponse("4010800", DanaErrorMessage.INVALID_SIGNATURE)
    GENERAL_ERROR = AccountInquiryResponse("5000800", DanaErrorMessage.GENERAL_ERROR)
    INTERNAL_SERVER_ERROR = AccountInquiryResponse(
        "5000801", DanaErrorMessage.INTERNAL_SERVER_ERROR
    )


class MaxCreditorStatus:
    PASS = "pass"
    PENDING = "pending"
    NOT_PASS = "not_pass"


class DanaQueryTypeAccountInfo:
    DBR_ALLOWED = "DBR_ALLOWED"
    CREDITOR_CHECK = "CREDITOR_CHECK"
    DBR_INSTALLMENT_CHECK = "DBR_INSTALLMENT_CHECK"


class DanaDisbursementMethod(object):
    BALANCE = "BALANCE"
    BANK_ACCOUNT = "BANK_ACCOUNT"


class DanaInstallmentType(object):
    WEEKLY = "WEEKLY"
    BIWEEKLY = "BIWEEKLY"
    MONTHLY = "MONTHLY"

    @classmethod
    def values(cls):
        return {cls.WEEKLY, cls.BIWEEKLY, cls.MONTHLY}
