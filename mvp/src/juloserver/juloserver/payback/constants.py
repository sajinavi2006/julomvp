from builtins import object
from collections import namedtuple


class Messages(object):
    PAYMENT_RECEIVED = (
        "Pembayaran tagihan JULO Anda %s tlh diterima."
        " Lakukan pembayaran tepat waktu utk mendapatkan Cashback! dan"
        " Berikan rating 5 di bit.ly/juloapp")
    PAYMENT_RECEIVED_TEMPLATE_CODE = "payment_received"


class CashbackPromoConst(object):
    EMAIL_TYPE_REQUESTER_NOTIF = 'requester_notif'
    EMAIL_TYPE_APPROVER_NOTIF = 'approvers_notif'
    EMAIL_TYPE_APPROVAL = 'approval'
    EMAIL_TYPE_REJECTION = 'rejection'


class WaiverConst(object):
    MINIMUM_DPD = -5 #remove validation for bucket 1
    ACTIVE_STATUS = 'active'
    EXPIRED_STATUS = 'expired'
    IMPLEMENTED_STATUS = 'implemented'


class GopayAccountStatusMessageConst(object):
    status = {
        'ENABLED': 'Akun Anda sudah terhubung',
        'PENDING': 'Akun Anda sedang dalam proses registrasi',
        'EXPIRED': 'Sesi Anda sudah habis, silahkan coba kembali',
        'DISABLED': 'Akun Anda belum terhubung'
    }


class GopayAccountStatusConst(object):
    ENABLED = 'ENABLED'
    PENDING = 'PENDING'
    EXPIRED = 'EXPIRED'
    DISABLED = 'DISABLED'


class GopayTransactionStatusConst(object):
    SETTLEMENT = 'settlement'
    PENDING = 'pending'
    DENY = 'deny'
    EXPIRED = 'expired'


class GopayAccountFailedResponseCodeConst(object):
    USER_NOT_FOUND = '105'
    WALLET_IS_BLOCKED = '112'


class GopayAccountErrorConst(object):
    DEACTIVATED = 'Akun Anda telah di deaktivasi'
    ACCOUNT_NOT_REGISTERED = 'Akun GoPay Anda belum terhubung/tidak terdaftar'


class MobileFeatureNameConst:
    GOPAY_INIT_REDIRECT_URL = 'gopay_init_redirect_url'


class FeatureSettingNameConst:
    GOPAY_CHANGE_URL = 'gopay_change_url'
    CHANGE_PUBLIC_KEY_DANA_BILLER = 'change_public_key_dana_biller'
    DANA_BILLER_PRODUCT = 'dana_biller_product'
    CHANGE_CIMB_VA_CREDENTIALS = 'change_cimb_va_credentials'
    CHANGE_DOKU_SNAP_CREDENTIALS = 'change_doku_snap_credentials'
    CHANGE_ONEKLIK_SNAP_CREDENTIALS = 'change_oneklik_snap_credentials'


class DanaBillerStatusCodeConst:
    SUCCESS = '10'
    INVALID_DESTINATION = '20'
    BILL_NOT_AVAILABLE = '26'
    TRANSACTION_FAILED = '27'
    GENERAL_ERROR = '99'
    DATA_NOT_FOUND = '28'
    ORDER_NOT_FOUND = '40'


class CIMBSnapResponseMessage:
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
    VA_NOT_FOUND = "Invalid Bill/Virtual Account [Not Found]"
    INVALID_TIMESTAMP_FORMAT = "invalid timestamp format"


class CIMBSnapPaymentResponseCodeAndMessage:
    PaymentResponse = namedtuple('PaymentResponse', ['code', 'message'])

    SUCCESS = PaymentResponse("2002500", CIMBSnapResponseMessage.SUCCESSFUL)
    GENERAL_ERROR = PaymentResponse("5002500", CIMBSnapResponseMessage.GENERAL_ERROR)
    INVALID_TOKEN = PaymentResponse("4012501", CIMBSnapResponseMessage.INVALID_TOKEN)
    INVALID_AMOUNT = PaymentResponse("4042513", CIMBSnapResponseMessage.INVALID_AMOUNT)
    UNAUTHORIZED_SIGNATURE = PaymentResponse("4012500",
                                             CIMBSnapResponseMessage.UNAUTHORIZED_SIGNATURE)
    INVALID_MANDATORY_FIELD = PaymentResponse(
        "4002502", CIMBSnapResponseMessage.INVALID_MANDATORY_FIELD
    )
    INVALID_FIELD_FORMAT = PaymentResponse("4002501", CIMBSnapResponseMessage.INVALID_FIELD_FORMAT)
    EXTERNAL_ID_CONFLICT = PaymentResponse("4092500", CIMBSnapResponseMessage.EXTERNAL_ID_CONFLICT)
    PAID_BILL = PaymentResponse("4042514", CIMBSnapResponseMessage.PAID_BILL)
    VA_NOT_FOUND = PaymentResponse("4042512", CIMBSnapResponseMessage.VA_NOT_FOUND)
    INCONSISTENT_REQUEST = PaymentResponse("4042518", CIMBSnapResponseMessage.INCONSISTENT_REQUEST)


class CimbVAConst:
    MINIMUM_TRANSFER_AMOUNT = 10000
    PARTNER_SERVICE_ID = '2051'
    CHANNEL_ID = '95211'


class CimbVAResponseCodeConst:
    SUCCESS = '200'

    PAYMENT_SUCCESS = SUCCESS + '26' + '00'


class RedisKey(object):
    CIMB_CLIENT_AUTH_TOKEN = 'payback:cimb_client_auth_token'


EMAIL_EXCLUDED_PAYBACK_SERVICES = ["cashback", "julover", "loyalty_point", "grab", "dana"]
