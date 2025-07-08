from builtins import object
from collections import namedtuple

NOT_RETRY_ROBOCALL_STATUS = ['answered', 'ringing', 'started', 'completed']


class BcaConst(object):
    MINIMUM_TRANSFER_AMOUNT = 10000


class FaspayUrl(object):
    CREATE_TRANSACTION_DATA = '/cvr/300011/10'
    UPDATE_TRANSACTION_DATA = '/cvr/100036/10'


class SnapStatus:
    SUCCESS = "00"
    FAILED = "01"


class BcaSnapErrorMessage:
    SUCCESS = "Success"
    SUCCESSFUL = "Successful"
    GENERAL_ERROR = "General Error"
    INVALID_TOKEN = "Invalid Token (B2B)"
    INVALID_AMOUNT = "Invalid Amount"
    UNAUTHORIZED_SIGNATURE = "Unauthorized. [Signature]"
    UNAUTHORIZED_CLIENT = "Unauthorized. [Unknown client]"
    INVALID_MANDATORY_FIELD = "Invalid Mandatory Field"
    INVALID_FIELD_FORMAT = "Invalid Field Format"
    EXTERNAL_ID_CONFLICT = "Conflict"
    PAID_BILL = "Paid Bill"
    INCONSISTENT_REQUEST = "Inconsistent Request"
    BILL_OR_VA_NOT_FOUND = "Invalid Bill/Virtual Account [Not Found]"
    INVALID_TIMESTAMP_FORMAT = "invalid timestamp format"


class SnapInquiryResponseCodeAndMessage:
    InquiryResponse = namedtuple('InquiryResponse', ['code', 'message'])

    SUCCESS = InquiryResponse("2002400", BcaSnapErrorMessage.SUCCESS)
    SUCCESSFUL = InquiryResponse("2002400", BcaSnapErrorMessage.SUCCESSFUL)
    GENERAL_ERROR = InquiryResponse("5002400", BcaSnapErrorMessage.GENERAL_ERROR)
    INVALID_TOKEN = InquiryResponse("4012401", BcaSnapErrorMessage.INVALID_TOKEN)
    UNAUTHORIZED_SIGNATURE = InquiryResponse("4012400", BcaSnapErrorMessage.UNAUTHORIZED_SIGNATURE)
    INVALID_MANDATORY_FIELD = InquiryResponse(
        "4002402", BcaSnapErrorMessage.INVALID_MANDATORY_FIELD
    )
    INVALID_FIELD_FORMAT = InquiryResponse("4002401", BcaSnapErrorMessage.INVALID_FIELD_FORMAT)
    EXTERNAL_ID_CONFLICT = InquiryResponse("4092400", BcaSnapErrorMessage.EXTERNAL_ID_CONFLICT)
    PAID_BILL = InquiryResponse("4042414", BcaSnapErrorMessage.PAID_BILL)
    BILL_OR_VA_NOT_FOUND = InquiryResponse("4042412", BcaSnapErrorMessage.BILL_OR_VA_NOT_FOUND)
    UNAUTHORIZED_CLIENT = InquiryResponse("4012400", BcaSnapErrorMessage.UNAUTHORIZED_CLIENT)


class BcaSnapPaymentResponseCodeAndMessage:
    PaymentResponse = namedtuple('PaymentResponse', ['code', 'message'])

    SUCCESS = PaymentResponse("2002500", BcaSnapErrorMessage.SUCCESS)
    GENERAL_ERROR = PaymentResponse("5002500", BcaSnapErrorMessage.GENERAL_ERROR)
    INVALID_TOKEN = PaymentResponse("4012501", BcaSnapErrorMessage.INVALID_TOKEN)
    INVALID_AMOUNT = PaymentResponse("4042513", BcaSnapErrorMessage.INVALID_AMOUNT)
    UNAUTHORIZED_SIGNATURE = PaymentResponse("4012500", BcaSnapErrorMessage.UNAUTHORIZED_SIGNATURE)
    INVALID_MANDATORY_FIELD = PaymentResponse(
        "4002502", BcaSnapErrorMessage.INVALID_MANDATORY_FIELD
    )
    INVALID_FIELD_FORMAT = PaymentResponse("4002501", BcaSnapErrorMessage.INVALID_FIELD_FORMAT)
    EXTERNAL_ID_CONFLICT = PaymentResponse("4092500", BcaSnapErrorMessage.EXTERNAL_ID_CONFLICT)
    PAID_BILL = PaymentResponse("4042514", BcaSnapErrorMessage.PAID_BILL)
    BILL_OR_VA_NOT_FOUND = PaymentResponse("4042512", BcaSnapErrorMessage.BILL_OR_VA_NOT_FOUND)
    INCONSISTENT_REQUEST = PaymentResponse("4042518", BcaSnapErrorMessage.INCONSISTENT_REQUEST)
    UNAUTHORIZED_CLIENT = PaymentResponse("4012500", BcaSnapErrorMessage.UNAUTHORIZED_CLIENT)


class SnapTokenResponseCodeAndMessage:
    TokenResponse = namedtuple('TokenResponse', ['code', 'message'])

    SUCCESS = TokenResponse("2007300", BcaSnapErrorMessage.SUCCESS)
    SUCCESSFUL = TokenResponse("2007300", BcaSnapErrorMessage.SUCCESSFUL)
    UNAUTHORIZED_SIGNATURE = TokenResponse("4017300", BcaSnapErrorMessage.UNAUTHORIZED_SIGNATURE)
    UNAUTHORIZED_CLIENT = TokenResponse("4017300", BcaSnapErrorMessage.UNAUTHORIZED_CLIENT)
    INVALID_MANDATORY_FIELD = TokenResponse("4007302", BcaSnapErrorMessage.INVALID_MANDATORY_FIELD)
    INVALID_FIELD_FORMAT = TokenResponse("4007301", BcaSnapErrorMessage.INVALID_FIELD_FORMAT)
    INVALID_TIMESTAMP_FORMAT = TokenResponse(
        "4007301", BcaSnapErrorMessage.INVALID_TIMESTAMP_FORMAT
    )


class SnapReasonMultilanguage:
    Reason = namedtuple('Reason', ['english', 'indonesia'])

    INVALID_TOKEN = Reason('invalid token', 'token tidak valid')
    INVALID_AMOUNT = Reason('invalid amount', 'jumlah yang dibayar tidak valid')
    INVALID_MANDATORY_FIELD = Reason('field {} is mandatory', 'field {} tidak boleh kosong')
    INVALID_FIELD_FORMAT = Reason('invalid field format {}', 'format field {} tidak valid')
    NULL_EXTERNAL_ID = Reason('X-EXTERNAL-ID cannot null', 'X-EXTERNAL-ID tidak boleh kosong')
    DUPLICATE_EXTERNAL_ID = Reason(
        'cannot use the same X-EXTERNAL-ID', 'tidak boleh menggunakan X-EXTERNAL-ID yang sama'
    )
    INVALID_SIGNATURE = Reason('invalid signature', 'signature tidak valid')
    PAID_BILL = Reason('paid bill', 'bill telah dibayar')
    BILL_NOT_FOUND = Reason('bill not found', 'bill tidak ditemukan')
    VA_NOT_FOUND = Reason('virtual account not found', 'virtual account tidak ditemukan')
    VA_NOT_HAVE_BILL = Reason(
        'virtual account doesnt have the bill', 'virtual account tidak mempunyai tagihan'
    )
    SUCCESS = Reason('success', 'sukses')
    INCONSISTENT_REQUEST = Reason('inconsistent request', 'request tidak consistent')
    SUCCESSFUL = Reason('successful', 'sukses')


class FaspaySnapErrorMessage:
    SUCCESS = "Success"
    IN_PROGRESS = "Request In Progress"
    BAD_REQUEST = "Bad Request"
    INVALID_FIELD_FORMAT = "Invalid Field Format"
    INVALID_MANDATORY_FIELD = "Missing Mandatory Field"
    UNAUTHORIZED_SIGNATURE = "Unauthorized Signature"
    UNAUTHORIZED_CLIENT = "Unauthorized. [Unknown client]"
    INVALID_TOKEN = "Invalid Token (B2B)"
    INVALID_CUSTOMER_TOKEN = "Invalid Customer Token"
    TOKEN_NOT_FOUND = "Token Not Found (B2B)"
    CUSTOMER_TOKEN_NOT_FOUND = "Customer Token Not Found"
    EXPIRED_TRANSACTION = "Transaction Expired"
    FEATURE_NOT_ALLOWED = "Feature Not Allowed"
    EXCEEDS_TRANSACTION_LIMIT = "Exceeds Transaction Amount Limit"
    SUSPECTED_FRAUD = "Suspected Fraud"
    TRANSACTION_NOT_FOUND = "Transaction Not Found"
    BILL_OR_VA_NOT_FOUND = "Bill not found"
    BILL_OR_VA_OR_CUSTOMER_INVALID = "Invalid Card/Account/Customer/Virtual Account"
    BILL_PAID = "Bill has been paid"
    GENERAL_ERROR = "General Error"
    INVALID_AMOUNT = "Invalid Amount"
    CONFLICT = "Conflict"
    INCONSISTENT_REQUEST = "Inconsistent Request"


class FaspaySnapInquiryResponseCodeAndMessage:
    InquiryResponse = namedtuple('InquiryResponse', ['code', 'message'])

    SUCCESS = InquiryResponse("2002400", FaspaySnapErrorMessage.SUCCESS)
    IN_PROGRESS = InquiryResponse("2022400", FaspaySnapErrorMessage.IN_PROGRESS)
    BAD_REQUEST = InquiryResponse("4002400", FaspaySnapErrorMessage.BAD_REQUEST)
    INVALID_FIELD_FORMAT = InquiryResponse("4002401", FaspaySnapErrorMessage.INVALID_FIELD_FORMAT)
    INVALID_MANDATORY_FIELD = InquiryResponse(
        "4002402", FaspaySnapErrorMessage.INVALID_MANDATORY_FIELD
    )
    UNAUTHORIZED_SIGNATURE = InquiryResponse(
        "4012400", FaspaySnapErrorMessage.UNAUTHORIZED_SIGNATURE
    )
    UNAUTHORIZED_CLIENT = InquiryResponse("4012400", FaspaySnapErrorMessage.UNAUTHORIZED_CLIENT)
    INVALID_TOKEN = InquiryResponse("4012401", FaspaySnapErrorMessage.INVALID_TOKEN)
    INVALID_CUSTOMER_TOKEN = InquiryResponse(
        "4012402", FaspaySnapErrorMessage.INVALID_CUSTOMER_TOKEN
    )
    CUSTOMER_TOKEN_NOT_FOUND = InquiryResponse(
        "4012403", FaspaySnapErrorMessage.CUSTOMER_TOKEN_NOT_FOUND
    )
    EXPIRED_TRANSACTION = InquiryResponse("4032400", FaspaySnapErrorMessage.EXPIRED_TRANSACTION)
    FEATURE_NOT_ALLOWED = InquiryResponse("4032401", FaspaySnapErrorMessage.FEATURE_NOT_ALLOWED)
    EXCEEDS_TRANSACTION_LIMIT = InquiryResponse(
        "4032402", FaspaySnapErrorMessage.EXCEEDS_TRANSACTION_LIMIT
    )
    SUSPECTED_FRAUD = InquiryResponse("4032403", FaspaySnapErrorMessage.SUSPECTED_FRAUD)
    TRANSACTION_NOT_FOUND = InquiryResponse("4042401", FaspaySnapErrorMessage.TRANSACTION_NOT_FOUND)
    BILL_OR_VA_OR_CUSTOMER_INVALID = InquiryResponse(
        "4042411", FaspaySnapErrorMessage.BILL_OR_VA_OR_CUSTOMER_INVALID
    )
    BILL_OR_VA_NOT_FOUND = InquiryResponse("4042412", FaspaySnapErrorMessage.BILL_OR_VA_NOT_FOUND)
    BILL_PAID = InquiryResponse("4042414", FaspaySnapErrorMessage.BILL_PAID)
    INCONSISTENT_REQUEST = InquiryResponse("4042400", FaspaySnapErrorMessage.INCONSISTENT_REQUEST)
    EXTERNAL_ID_CONFLICT = InquiryResponse("4092400", FaspaySnapErrorMessage.CONFLICT)

    GENERAL_ERROR = InquiryResponse("5002400", BcaSnapErrorMessage.GENERAL_ERROR)


class SnapVendorChoices:
    BCA = 'bca'
    ALL = ((BCA, 'Bank Central Asia'),)
    CIMB = 'cimb'
    DOKU = 'doku'
    ONEKLIK = 'oneklik'
    FASPAY = 'faspay'


EXPIRY_TIME_TOKEN_BCA_SNAP = 900  # in seconds
EXPIRY_TIME_TOKEN_CIMB_SNAP = 900  # in seconds
EXPIRY_TIME_TOKEN_DOKU_SNAP = 900  # in seconds
EXPIRY_TIME_TOKEN_ONEKLIK_SNAP = 900  # in seconds
BCA_SNAP_PARTNER_NAME = 'bca_snap'


class ErrorDetail:
    NULL = 'This field may not be null.'
    BLANK = 'This field may not be blank.'
    REQUIRED = 'This field is required.'

    @classmethod
    def mandatory_field_errors(cls):
        return {cls.NULL, cls.BLANK, cls.REQUIRED}


class FaspayPaymentChannelCode(object):
    MAYBANK = '408'
    BRI = '800'
    MANDIRI = '802'
    PERMATA = '402'
    BCA = '702'
    BNI = '801'
    INDOMARET = '706'
    ALFAMART = '707'


class FaspaySnapPaymentResponseCodeAndMessage:
    PaymentResponse = namedtuple('PaymentResponse', ['code', 'message'])

    SUCCESS = PaymentResponse("2002500", FaspaySnapErrorMessage.SUCCESS)
    IN_PROGRESS = PaymentResponse("2022500", FaspaySnapErrorMessage.IN_PROGRESS)
    BAD_REQUEST = PaymentResponse("4002500", FaspaySnapErrorMessage.BAD_REQUEST)
    INVALID_FIELD_FORMAT = PaymentResponse("4002501", FaspaySnapErrorMessage.INVALID_FIELD_FORMAT)
    INVALID_MANDATORY_FIELD = PaymentResponse(
        "4002502", FaspaySnapErrorMessage.INVALID_MANDATORY_FIELD
    )
    UNAUTHORIZED_SIGNATURE = PaymentResponse(
        "4012500", FaspaySnapErrorMessage.UNAUTHORIZED_SIGNATURE
    )
    UNAUTHORIZED_CLIENT = PaymentResponse("4012500", FaspaySnapErrorMessage.UNAUTHORIZED_CLIENT)
    INVALID_TOKEN = PaymentResponse("4012501", FaspaySnapErrorMessage.INVALID_TOKEN)
    INVALID_CUSTOMER_TOKEN = PaymentResponse(
        "4012502", FaspaySnapErrorMessage.INVALID_CUSTOMER_TOKEN
    )
    CUSTOMER_TOKEN_NOT_FOUND = PaymentResponse(
        "4012503", FaspaySnapErrorMessage.CUSTOMER_TOKEN_NOT_FOUND
    )
    EXPIRED_TRANSACTION = PaymentResponse("4032500", FaspaySnapErrorMessage.EXPIRED_TRANSACTION)
    FEATURE_NOT_ALLOWED = PaymentResponse("4032501", FaspaySnapErrorMessage.FEATURE_NOT_ALLOWED)
    EXCEEDS_TRANSACTION_LIMIT = PaymentResponse(
        "4032502", FaspaySnapErrorMessage.EXCEEDS_TRANSACTION_LIMIT
    )
    SUSPECTED_FRAUD = PaymentResponse("4032503", FaspaySnapErrorMessage.SUSPECTED_FRAUD)
    TRANSACTION_NOT_FOUND = PaymentResponse("4042501", FaspaySnapErrorMessage.TRANSACTION_NOT_FOUND)
    BILL_OR_VA_NOT_FOUND = PaymentResponse("4042512", FaspaySnapErrorMessage.BILL_OR_VA_NOT_FOUND)
    BILL_PAID = PaymentResponse("4042514", FaspaySnapErrorMessage.BILL_PAID)
    INVALID_AMOUNT = PaymentResponse("4042513", FaspaySnapErrorMessage.INVALID_AMOUNT)
    EXTERNAL_ID_CONFLICT = PaymentResponse("4092500", FaspaySnapErrorMessage.CONFLICT)
    INCONSISTENT_REQUEST = PaymentResponse("4042500", FaspaySnapErrorMessage.INCONSISTENT_REQUEST)

    GENERAL_ERROR = PaymentResponse("5002500", BcaSnapErrorMessage.GENERAL_ERROR)


MINIMUM_TRANSFER_AMOUNT = 10000
MAX_TASK_RETRY = 3


class SnapPaymentNotificationResponseCodeAndMessage:
    PaymentNotificationReason = namedtuple('PaymentNotificationReason', ['code', 'message'])
    INVALID_TOKEN = PaymentNotificationReason("4012501", BcaSnapErrorMessage.INVALID_TOKEN)
    UNAUTHORIZED_SIGNATURE = PaymentNotificationReason(
        "4012500", BcaSnapErrorMessage.UNAUTHORIZED_SIGNATURE
    )
    INVALID_MANDATORY_FIELD = PaymentNotificationReason(
        "4002502", BcaSnapErrorMessage.INVALID_MANDATORY_FIELD
    )
    INVALID_FIELD_FORMAT = PaymentNotificationReason(
        "4002501", BcaSnapErrorMessage.INVALID_FIELD_FORMAT
    )
    INVALID_AMOUNT = PaymentNotificationReason("4042513", BcaSnapErrorMessage.INVALID_AMOUNT)
    EXTERNAL_ID_CONFLICT = PaymentNotificationReason(
        "4002500", BcaSnapErrorMessage.EXTERNAL_ID_CONFLICT
    )
    VA_NOT_FOUND = PaymentNotificationReason("4002500", BcaSnapErrorMessage.BILL_OR_VA_NOT_FOUND)
    PAID_BILL = PaymentNotificationReason("4002500", BcaSnapErrorMessage.PAID_BILL)
    SUCCESS = PaymentNotificationReason("2002500", BcaSnapErrorMessage.SUCCESS)
    GENERAL_ERROR = PaymentNotificationReason("5002500", BcaSnapErrorMessage.GENERAL_ERROR)


class VonageOutboundCall:
    STATUS_WITH_DETAIL = ['failed', 'rejected', 'unanswered']
