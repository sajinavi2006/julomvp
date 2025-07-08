from builtins import object
from http import HTTPStatus


class NameBankValidationVendors(object):
    XENDIT = 'Xendit'
    XFERS = 'Xfers'
    INSTAMONEY = 'Instamoney'
    MANUAL = 'Manual'
    PAYMENT_GATEWAY = 'PG'
    DEFAULT = XFERS
    VENDOR_LIST = [INSTAMONEY, XFERS, PAYMENT_GATEWAY]
    VENDOR_LIST_2 = [XFERS, INSTAMONEY]


class NameBankValidationConst(object):
    # in percent
    NAME_SIMILARITY_THRESHOLD = 90


class DisbursementVendors(object):
    BCA = 'Bca'
    XENDIT = 'Xendit'
    XFERS = 'Xfers'
    INSTAMONEY = 'Instamoney'
    MANUAL = 'Manual'
    VENDOR_LIST = [INSTAMONEY, XFERS]
    VENDOR_LIST_2 = [INSTAMONEY]
    VALID_LIST = [BCA, XFERS]
    DANA_MANUAL = 'Dana Manual'
    AYOCONNECT = 'Ayoconnect'
    PG = 'PG'


class DisbursementVendorStatus(object):
    ACTIVE = 'active'
    INACTIVE = 'inactive'


class NameBankValidationStatus(object):
    from juloserver.julo.statuses import ApplicationStatusCodes
    INITIATED = 'INITIATED'
    PENDING = 'PENDING'
    SUCCESS = 'SUCCESS'
    NAME_INVALID = 'NAME_INVALID'
    BANK_ACCOUNT_INVALID = 'BANK_ACCOUNT_INVALID'
    FAILED = 'FAILED'
    SKIPPED_STATUSES = [PENDING, SUCCESS]
    FAILED_STATUSES = [NAME_INVALID, FAILED]
    APPLICATION_STATUSES = \
        [ApplicationStatusCodes.ACTIVATION_CALL_SUCCESS_AND_BANK_VALIDATE_ONGOING]
    OLD_VERSION_APPS = "<3.10.0"
    INVALID_NOTE = "Failed validate Name Bank Account or use old version of apps, used version {}"
    SUSPECT_VA_LENGTH = 16
    EXCEPTIONAL_BANK_CODE = ['200']  # Bank Tabungan Negara (BTN)


class DisbursementStatus(object):
    INITIATED = 'INITIATED'
    PENDING = 'PENDING'
    COMPLETED = 'COMPLETED'
    FAILED = 'FAILED'
    INSUFICIENT_BALANCE = 'INSUFICIENT BALANCE'
    SUFFICIENT_BALANCE = 'sufficient balance'
    SKIPPED_STATUSES = [PENDING, COMPLETED]
    CHECKING_STATUSES = [FAILED, PENDING]


class XfersDisbursementStep(object):
    FIRST_STEP = 1  # transfer from jtp to jtf
    SECOND_STEP = 2  # transfer from jtf to customer


class XenditDisbursementStep(object):
    FIRST_STEP = 1
    SECOND_STEP = 2


class AyoconnectDisbursementStep(object):
    FIRST_STEP = 1
    SECOND_STEP = 2


class PaymentgatewayDisbursementStep(object):
    FIRST_STEP = 1
    SECOND_STEP = 2


class MoneyFlow(object):
    NEW_XFERS = 'New_Xfers'


class RedisKey(object):
    BCA_AUTH_TOKEN_HASH = 'disbursement:bca_client_auth_token_hash'
    BCA_AUTH_TOKEN_TYPE = 'disbursement:bca_client_auth_token_type'


class GopayAlertDefault:
    CHANNEL = '#partner_balance'
    THRESHOLD = 30000000
    MESSAGE = '<!here> Gopay available balance {current_balance} is ' \
              'less then threshold {threshold}. Please top up!'


class AyoconnectConst(object):
    RETRYABLE_STATUS_CODES = {HTTPStatus.UNAUTHORIZED, HTTPStatus.REQUEST_TIMEOUT}
    DISBURSEMENT_STATUS_PROCESSING = 0
    DISBURSEMENT_STATUS_SUCCESS = 1
    DISBURSEMENT_STATUS_REFUNDED = 2
    DISBURSEMENT_STATUS_CANCELLED = 3
    DISBURSEMENT_STATUS_FAILED = 4

    DISBURSEMENT_STATUS = [
        DISBURSEMENT_STATUS_SUCCESS,
        DISBURSEMENT_STATUS_CANCELLED,
        DISBURSEMENT_STATUS_FAILED,
        DISBURSEMENT_STATUS_REFUNDED
    ]

    DISBURSEMENT_MAP_STATUS = {
        DISBURSEMENT_STATUS_FAILED: DisbursementStatus.FAILED,
        DISBURSEMENT_STATUS_PROCESSING: DisbursementStatus.PENDING,
        DISBURSEMENT_STATUS_SUCCESS: DisbursementStatus.COMPLETED,
        DISBURSEMENT_STATUS_CANCELLED: DisbursementStatus.FAILED,
        DISBURSEMENT_STATUS_REFUNDED: DisbursementStatus.FAILED
    }

    MAX_FAILED_RETRIES = 0

    BENEFICIARY_RETRY_LIMIT = 3

    PERMISSIBLE_BALANCE_LIMIT = 1000000000

    INSUFFICIENT_BALANCE_MESSAGE = 'Account does not have sufficient balance'

    DEFAULT_RETRY_DELAY_IN_HOUR = 1
    DEFAULT_RETRY_DELAY_IN_MIN = 5


class AyoconnectBeneficiaryStatus(object):
    INACTIVE = 0
    ACTIVE = 1
    DISABLED = 2
    BLOCKED = 3

    UNKNOWN_DUE_TO_UNSUCCESSFUL_CALLBACK = -1

    J1_RETRY_ADD_BENEFICIARY_STATUS = [
        DISABLED,
        BLOCKED,
        UNKNOWN_DUE_TO_UNSUCCESSFUL_CALLBACK
    ]


class PaymentGatewayVendorConst(object):
    AYOCONNECT = 'ayoconnect'


class AyoconnectErrorCodes(object):
    INVALID_BENEFICIARY_ID = "0903"
    INACTIVE_BENEFICIARY_ID = "0913"
    A_CORRELATION_ID_ALREADY_USED = "0325"
    TRANSACTION_ID_INVALID = "0310"

    # force switch to xfers
    SYSTEM_UNDER_MAINTENANCE = "0924"
    TRANSACTION_NOT_FOUND = "0213"
    INVALID_BENEFICIARY_ACCOUNT_NUMBER = "0901"
    ACCOUNT_INSUFFICIENT_BALANCE = "0401"
    SERVICE_UNAVAILABLE = "0226"
    ACCOUNT_NOT_FOUND = "0405"
    TRANSACTION_NOT_PERMITTED = "1005"
    ACCOUNT_IS_INACTIVE = "0504"
    BANK_CODE_INVALID = "0016"
    EWALLET_PROVIDER_ERROR = "0026"
    INVALID_OR_MISSING_FIELD_ERROR = "0505"
    TRANSFER_NOT_PERMITTED = "0929"
    TRANSACTION_AMOUNT_EXCEED_BALANCE = "0932"
    TRANSACTION_CANCELED_BY_PROVIDER = "0201"

    # can be retry
    EWALLET_FAILED = "0920"
    EWALLET_PROVIDER_ERROR_WHEN_PERFORMING = "0930"
    TRANSACTION_HAS_FAILED_FROM_BANK = "0921"
    ERROR_OCCURRED_FROM_BANK = "0024"

    GENERAL_FAILED_ADD_BENEFICIARY = 'GENERAL_FAILED_ADD_BENEFICIARY'
    FAILED_ACCESS_TOKEN = 'FAILED_ACCESS_TOKEN'

    J1_RECREATE_BEN_IDS = [
        GENERAL_FAILED_ADD_BENEFICIARY,
        INVALID_BENEFICIARY_ID,
        INACTIVE_BENEFICIARY_ID,
        INVALID_BENEFICIARY_ACCOUNT_NUMBER,
    ]

    J1_FORCE_SWITCH_TO_XFERS = [
        ACCOUNT_INSUFFICIENT_BALANCE,
        SYSTEM_UNDER_MAINTENANCE,
        TRANSACTION_NOT_FOUND,
        INVALID_BENEFICIARY_ACCOUNT_NUMBER,
        SERVICE_UNAVAILABLE,
        ACCOUNT_NOT_FOUND,
        TRANSACTION_NOT_PERMITTED,
        ACCOUNT_IS_INACTIVE,
        BANK_CODE_INVALID,
        EWALLET_PROVIDER_ERROR,
        INVALID_OR_MISSING_FIELD_ERROR,
        TRANSFER_NOT_PERMITTED,
        TRANSACTION_AMOUNT_EXCEED_BALANCE,
        TRANSACTION_CANCELED_BY_PROVIDER,
    ]

    J1_DISBURSE_RETRY_ERROR_CODES = [
        FAILED_ACCESS_TOKEN,
        ERROR_OCCURRED_FROM_BANK,
        TRANSACTION_HAS_FAILED_FROM_BANK,
        *J1_RECREATE_BEN_IDS,
        *J1_FORCE_SWITCH_TO_XFERS,
        EWALLET_FAILED,
        EWALLET_PROVIDER_ERROR_WHEN_PERFORMING,
    ]

    @classmethod
    def _get_error_code_types(cls):
        from juloserver.loan.services.lender_related import get_ayc_disbursement_feature_setting

        ayc_config = get_ayc_disbursement_feature_setting()
        return ayc_config.get('error_code_types', {})

    @classmethod
    def all_existing_error_codes(cls):
        """retry_codes = cls.all_existing_error_codes -  cls.force_switch_to_xfers_error_codes"""
        error_code_types = cls._get_error_code_types()
        return error_code_types.get('all', AyoconnectErrorCodes.J1_DISBURSE_RETRY_ERROR_CODES)

    @classmethod
    def force_switch_to_xfers_error_codes(cls):
        error_code_types = cls._get_error_code_types()
        return error_code_types.get(
            'force_switch_to_xfers', AyoconnectErrorCodes.J1_FORCE_SWITCH_TO_XFERS
        )


class AyoconnectURLs(object):
    DISBURSEMENT_URL = "/api/v1/bank-disbursements/disbursement"
    DISBURSEMENT_STATUS_URL = "/api/v1/bank-disbursements/status"
    BENEFICIARY_URL = "/api/v1/bank-disbursements/beneficiary"
    ACCESS_TOKEN_URL = "/v1/oauth/client_credential/accesstoken"
    MERCHANT_BALANCE_URL = "/api/v1/merchants/balance"


class AyoconnectErrorReason(object):
    ERROR_BENEFICIARY_BLOCKED = "beneficiary status blocked"
    ERROR_BENEFICIARY_INACTIVE = "beneficiary status inactive"
    ERROR_BENEFICIARY_MISSING_OR_DISABLED = "beneficiary is missing or disabled"
    ERROR_TRANSACTION_NOT_FOUND = "transaction not found"
    ERROR_BENEFICIARY_REQUEST = "error when requesting beneficiary"
    SYSTEM_UNDER_MAINTENANCE = 'system under maintenance'


class AyoconnectFailoverXfersConst(object):
    STUCK_DAYS_BEFORE_FAILING_OVER = 1

    MAX_RETRIES_EXCEEDED = "use Xfers due to max_retries exceeded"
    ACCOUNT_INSUFFICIENT_BALANCE = "use Xfers due to insufficient balance"
    SYSTEM_UNDER_MAINTENANCE = "use Xfers due to Ayoconnect being under maintenance"
    TRANSACTION_NOT_FOUND = "Transaction was not found. Please check with Ayoconnect Team."
    INVALID_BENEFICIARY_ACCOUNT_NUMBER = "The Beneficiary account-number is invalid"
    SERVICE_UNAVAILABLE = (
        "Service unavailable, Please reach out to customer support for further assistance."
    )
    ACCOUNT_NOT_FOUND = "Account was not found"
    TRANSACTION_NOT_PERMITTED = "The transaction is not permitted"
    ACCOUNT_IS_INACTIVE = (
        "User account is inactive. Please reach out to customer support for further assistance."
    )
    BANK_CODE_INVALID = "Bank code is invalid"
    EWALLET_PROVIDER_ERROR = (
        "Ewallet provider error. Please reach out to customer support for further assistance."
    )
    INVALID_OR_MISSING_FIELD_ERROR = "Invalid or missing field value"
    TRANSFER_NOT_PERMITTED = "Transfer not permitted to this account."
    TRANSACTION_AMOUNT_EXCEED_BALANCE = (
        "The transaction amount exceeds the user's maximum ewallet balance capacity."
    )
    TRANSACTION_CANCELED_BY_PROVIDE = "Internal server error."

    J1_FORCE_SWITCH_MAPPING = {
        AyoconnectErrorCodes.ACCOUNT_INSUFFICIENT_BALANCE: ACCOUNT_INSUFFICIENT_BALANCE,
        AyoconnectErrorCodes.SYSTEM_UNDER_MAINTENANCE: SYSTEM_UNDER_MAINTENANCE,
        AyoconnectErrorCodes.TRANSACTION_NOT_FOUND: TRANSACTION_NOT_FOUND,
        AyoconnectErrorCodes.INVALID_BENEFICIARY_ACCOUNT_NUMBER: INVALID_BENEFICIARY_ACCOUNT_NUMBER,
        AyoconnectErrorCodes.SERVICE_UNAVAILABLE: SERVICE_UNAVAILABLE,
        AyoconnectErrorCodes.ACCOUNT_NOT_FOUND: ACCOUNT_NOT_FOUND,
        AyoconnectErrorCodes.TRANSACTION_NOT_PERMITTED: TRANSACTION_NOT_PERMITTED,
        AyoconnectErrorCodes.ACCOUNT_IS_INACTIVE: TRANSACTION_NOT_PERMITTED,
        AyoconnectErrorCodes.BANK_CODE_INVALID: TRANSACTION_NOT_PERMITTED,
        AyoconnectErrorCodes.EWALLET_PROVIDER_ERROR: EWALLET_PROVIDER_ERROR,
        AyoconnectErrorCodes.INVALID_OR_MISSING_FIELD_ERROR: INVALID_OR_MISSING_FIELD_ERROR,
        AyoconnectErrorCodes.TRANSFER_NOT_PERMITTED: TRANSFER_NOT_PERMITTED,
        AyoconnectErrorCodes.TRANSACTION_AMOUNT_EXCEED_BALANCE: TRANSACTION_AMOUNT_EXCEED_BALANCE,
        AyoconnectErrorCodes.TRANSACTION_CANCELED_BY_PROVIDER: TRANSACTION_CANCELED_BY_PROVIDE,
    }


class PaymentGatewayErrorReason(object):
    ERROR_BENEFICIARY_MISSING_OR_DISABLED = "beneficiary is missing or disabled"
    ERROR_TRANSACTION_NOT_FOUND = "transaction not found"
    ERROR_BENEFICIARY_REQUEST = "error when requesting beneficiary"
    SYSTEM_UNDER_MAINTENANCE = 'system under maintenance'


class PaymentGatewayConst(object):
    DISBURSEMENT_STATUS_PENDING = 'pending'
    DISBURSEMENT_STATUS_SUCCESS = 'success'
    DISBURSEMENT_STATUS_INITIAL = 'initialized'
    DISBURSEMENT_STATUS_FAILED = 'failed'

    DISBURSEMENT_MAP_STATUS = {
        DISBURSEMENT_STATUS_FAILED: DisbursementStatus.FAILED,
        DISBURSEMENT_STATUS_PENDING: DisbursementStatus.PENDING,
        DISBURSEMENT_STATUS_SUCCESS: DisbursementStatus.COMPLETED,
        DISBURSEMENT_STATUS_INITIAL: DisbursementStatus.PENDING,
    }


class DailyDisbursementLimitWhitelistConst(object):
    DOCUMENT_TYPE = 'daily_disbursement_limit_whitelist'
    FILE_UPLOAD_EXTENSIONS = ['text/xls', 'text/xlsx', 'text/csv']
    MAX_FILE_UPLOAD_SIZE_IN_MB = 10
    MAX_FILE_UPLOAD_SIZE = MAX_FILE_UPLOAD_SIZE_IN_MB * 1024 * 1024  # MB
    QUERY_SIZE = 10000
    FILE_HEADERS = ["customer_id", "source"]
