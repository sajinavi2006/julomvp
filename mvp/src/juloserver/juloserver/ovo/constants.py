from collections import namedtuple


class OvoConst(object):
    MERCHANT_NAME = 'JULO'
    MERCHANT_ID = 31932
    PAYMENT_METHOD_CODE = '1003'
    WHITELIST_OVO = 'whitelist_ovo'
    PAYMENT_METHOD_NAME = 'OVO'


class OvoTransactionStatus(object):
    POST_DATA_SUCCESS = 'POST DATA SUCCESS'
    PUSH_TO_PAY_SUCCESS = 'PUSH TO PAY SUCCESS'
    PAYMENT_NOTIFICATION_PENDING = 'PAYMENT_NOTIFICATION_PENDING'
    FAILED = 'FAILED'
    SUCCESS = 'SUCCESS'
    PAYMENT_FAILED = 'PAYMENT_FAILED'


class OvoUrl(object):
    CREATE_TRANSACTION_DATA = '/cvr/300011/10'
    PUSH_TO_PAY = '/pws/ovo_direct'
    INQUIRY_PAYMENT_STATUS = '/cvr/100004/10'


class OvoPaymentStatus(object):
    UNPROCESSED = '0'
    IN_PROCESS = '1'
    PAYMENT_SUCCESS = '2'
    PAYMENT_FAILED = '3'
    PAYMENT_REVERSAL = '4'
    NO_BILLS_FOUND = '5'
    PAYMENT_EXPIRED = '7'
    PAYMENT_CANCELED = '8'
    UNKNOWN = '9'

    RESPONSE = {
        '0': 'UNPROCESSED',
        '1': 'IN_PROCESS',
        '2': 'PAYMENT_SUCCESS',
        '3': 'PAYMENT_FAILED',
        '4': 'PAYMENT_REVERSAL',
        '5': 'NO_BILLS_FOUND',
        '7': 'PAYMENT_EXPIRED',
        '8': 'PAYMENT_CANCELED',
        '9': 'UNKNOWN'
    }

    RESPONSE_DESCRIPTION = {
        '00': 'Success',
        '14': 'Invalid Mobile Number',
        '17': 'Transaction Decline',
        '25': 'Transaction Not Found',
        '26': 'Transaction Failed',
        '40': 'Transaction Failed (duplicate invoice/ batch number/ reference number)',
        '54': 'Transaction Expired',
        '56': 'Card Blocked',
        '58': 'Transaction Not Allowed',
        '61': 'Exceed Limit Amount',
        '63': 'Security Violation',
        '64': 'Account Blocked',
        '65': 'Transaction Failed, Exceed Limit',
        '67': 'Below Minimum Limit',
        '68': 'Transaction Pending',
        '73': 'Transaction Reversed',
        '96': 'Invalid Processing Code'
    }


class OvoMobileFeatureName:
    OVO_REPAYMENT_COUNTDOWN = 'ovo_repayment_countdown'


class OvoWalletAccountStatusConst:
    ENABLED = 'ENABLED'
    PENDING = 'PENDING'
    DISABLED = 'DISABLED'
    FAILED = 'FAILED'


class OvoWalletRequestBindingResponseCodeAndMessage:
    OvoWalletBindingResponse = namedtuple('OvoWalletBindingResponse', ['code', 'message'])
    PHONE_NUMBER_REQUIRED = OvoWalletBindingResponse(
        405, "phone_number This field may not be blank."
    )
    UNAUTHORIZED = OvoWalletBindingResponse(406, "User is not allowed")
    ALREADY_REGISTERED = OvoWalletBindingResponse(407, "User is already registered")
    TIMEOUT = OvoWalletBindingResponse(408, "Timeout")
    ALREADY_REGISTERED_BY_OTHER_CUSTOMER1 = OvoWalletBindingResponse(
        409, "Transaction Not Permitted. OVO account already registered by another customer"
    )
    ALREADY_REGISTERED_BY_OTHER_CUSTOMER2 = OvoWalletBindingResponse(
        409, "Transaction Not Permitted. Account Already Registered"
    )
    ACCOUNT_BLOCKED = OvoWalletBindingResponse(
        410, "Transaction Not Permitted. OVO account blocked temporary"
    )
    ACCOUNT_NOT_AVAILABLE = OvoWalletBindingResponse(
        411, "Transaction Not Permitted. OVO account not available please register to ovo"
    )

    def get_doku_error_responses(self):
        return [
            self.TIMEOUT,
            self.ALREADY_REGISTERED_BY_OTHER_CUSTOMER1,
            self.ALREADY_REGISTERED_BY_OTHER_CUSTOMER2,
            self.ACCOUNT_BLOCKED,
            self.ACCOUNT_NOT_AVAILABLE,
        ]


class OvoErrorMessage:
    SUCCESSFUL = "Successful"
    GENERAL_ERROR = "General Error"
    BAD_REQUEST = "Bad Request"
    INVALID_TOKEN = "Invalid Token (B2B)"
    UNAUTHORIZED_SIGNATURE = "Unauthorized. [Signature]"
    NOT_FOUND = "Transaction Not Found"
    INVALID_FIELD_FORMAT = "Invalid Field Format"
    EXTERNAL_ID_CONFLICT = "Conflict"
    INVALID_MANDATORY_FIELD = 'Invalid Mandatory Field'
    INVALID_CUSTOMER_TOKEN = 'Invalid Token (B2B2C)'
    PAID_BILL = 'Paid Bill'


class OvoBindingResponseCodeAndMessage:
    BindingResponse = namedtuple('BindingResponse', ['code', 'message'])

    SUCCESSFUL = BindingResponse("2000700", OvoErrorMessage.SUCCESSFUL)
    GENERAL_ERROR = BindingResponse("5000700", OvoErrorMessage.GENERAL_ERROR)
    INVALID_TOKEN = BindingResponse("4010701", OvoErrorMessage.INVALID_TOKEN)
    UNAUTHORIZED_SIGNATURE = BindingResponse("4010700", OvoErrorMessage.UNAUTHORIZED_SIGNATURE)
    BAD_REQUEST = BindingResponse("4000701", OvoErrorMessage.BAD_REQUEST)
    INVALID_FIELD_FORMAT = BindingResponse("4000701", OvoErrorMessage.INVALID_FIELD_FORMAT)
    EXTERNAL_ID_CONFLICT = BindingResponse("4090700", OvoErrorMessage.EXTERNAL_ID_CONFLICT)
    NOT_FOUND = BindingResponse("4040701", OvoErrorMessage.NOT_FOUND)


class OvoStatus:
    SUCCESS = "SUCCESS"
    PENDING = "PENDING"
    FAILED = "FAILED"


class OvoPaymentResponseMessage:
    INSUFFICIENT_BALANCE = "Insufficient Fund"
    INVALID_CUSTOMER_TOKEN = "Invalid Customer Token"
    MAXIMUM_DEDUCTION_AMOUNT = "Exceeds Transaction Amount Limit"


class OvoPaymentErrors:
    NOT_FOUND = "Ovo wallet not found"
    BILL_NOT_FOUND = "Bill not found"
    INSUFFICIENT_BALANCE = "Insufficient balance"
    ALREADY_UNLINKED_FROM_APP = "Already unlinked from app"
    MAXIMUM_DEDUCTION_AMOUNT = "Amount exceeded customer limit"


OvoPaymentResponse = namedtuple('OvoPaymentResponse', ['code', 'message'])


class OvoPaymentErrorResponseCodeAndMessage:
    NOT_FOUND = OvoPaymentResponse(406, OvoPaymentErrors.NOT_FOUND)
    BILL_NOT_FOUND = OvoPaymentResponse(407, OvoPaymentErrors.BILL_NOT_FOUND)
    INSUFFICIENT_BALANCE = OvoPaymentResponse(408, OvoPaymentErrors.INSUFFICIENT_BALANCE)
    ALREADY_UNLINKED_FROM_APP = OvoPaymentResponse(409, OvoPaymentErrors.ALREADY_UNLINKED_FROM_APP)
    MAXIMUM_DEDUCTION_AMOUNT = OvoPaymentResponse(410, OvoPaymentErrors.MAXIMUM_DEDUCTION_AMOUNT)


class OvoWalletTransactionStatusConst:
    SUCCESS = "SUCCESS"
    PENDING = "PENDING"
    FAILED = "FAILED"


MINIMUM_AMOUNT_PAYMENT = 10000
AUTODEBET_MINIMUM_AMOUNT_PAYMENT = 1
AUTODEBET_MAXIMUM_AMOUNT_PAYMENT = 2000000


class OvoPaymentNotificationResponseCodeAndMessage:
    PaymentNotificationResponse = namedtuple('PaymentNotificationResponse', ['code', 'message'])

    SUCCESSFUL = PaymentNotificationResponse('2005600', 'Request has been processed successfully')
    GENERAL_ERROR = PaymentNotificationResponse('5005600', OvoErrorMessage.GENERAL_ERROR)
    BAD_REQUEST = PaymentNotificationResponse("4005601", OvoErrorMessage.BAD_REQUEST)
    INVALID_TOKEN = PaymentNotificationResponse("4015601", OvoErrorMessage.INVALID_TOKEN)
    UNAUTHORIZED_SIGNATURE = PaymentNotificationResponse(
        "4015600", OvoErrorMessage.UNAUTHORIZED_SIGNATURE
    )
    INVALID_FIELD_FORMAT = PaymentNotificationResponse(
        "4005601", OvoErrorMessage.INVALID_FIELD_FORMAT
    )
    EXTERNAL_ID_CONFLICT = PaymentNotificationResponse(
        "4095600", OvoErrorMessage.EXTERNAL_ID_CONFLICT
    )
    NOT_FOUND = PaymentNotificationResponse("4045601", OvoErrorMessage.NOT_FOUND)
    INVALID_MANDATORY_FIELD = PaymentNotificationResponse(
        "4005602", OvoErrorMessage.INVALID_MANDATORY_FIELD
    )
    INVALID_CUSTOMER_TOKEN = PaymentNotificationResponse(
        "4015602", OvoErrorMessage.INVALID_CUSTOMER_TOKEN
    )
    PAID_BILL = PaymentNotificationResponse("4005600", OvoErrorMessage.PAID_BILL)


class OvoPaymentType:
    SALE = "SALE"
    RECURRING = "RECURRING"
