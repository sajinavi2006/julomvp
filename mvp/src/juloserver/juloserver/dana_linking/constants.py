from collections import namedtuple


class RedisKey:
    CLIENT_AUTH_TOKEN = 'dana_linking:auth_token'


class DanaWalletAccountStatusConst:
    ENABLED = 'ENABLED'
    PENDING = 'PENDING'
    DISABLED = 'DISABLED'


GRANT_TYPE = {"activation": "AUTHORIZATION_CODE", "refresh_token": "REFRESH_TOKEN"}


class ErrorMessage:
    GENERAL_ERROR = "Terjadi kesalahan silahkan ulangi beberapa saat lagi"
    DANA_NOT_FOUND = "Akun dana tidak ditemukan"
    PUBLIC_USER_ID_NULL = "Public user id null"


class ResponseMessage:
    DEACTIVATED = "Akun Anda telah di deaktivasi"
    BILL_NOT_FOUND = "Tidak ada tagihan"


EXPIRY_TIME_TOKEN_DANA = 3600  # in seconds


class DanaResponseMessage:
    GENERAL_ERROR = "General Error"
    INTERNAL_SERVER = "Internal Server Error"
    INVALID_FIELD_FORMAT = "Invalid Field Format"
    INVALID_MANDATORY_FIELD = "Invalid Mandatory Field"
    SUCCESSFUL = "Successful"
    UNAUTHORIZED = "Unauthorized."
    INVALID_TOKEN = "Invalid Token (B2B)"
    TRANSACTION_NOT_FOUND = "Transaction Not Found"


class DanaAccessTokenResponseCodeAndMessage:
    AccessTokenResponse = namedtuple('AccessTokenResponse', ['code', 'message'])

    SUCCESS = AccessTokenResponse("2007300", DanaResponseMessage.SUCCESSFUL)
    GENERAL_ERROR = AccessTokenResponse("5007300", DanaResponseMessage.GENERAL_ERROR)
    INTERNAL_SERVER = AccessTokenResponse("5007301", DanaResponseMessage.INTERNAL_SERVER)
    UNAUTHORIZED = AccessTokenResponse("4017300", DanaResponseMessage.UNAUTHORIZED)
    INVALID_MANDATORY_FIELD = AccessTokenResponse(
        "4002402", DanaResponseMessage.INVALID_MANDATORY_FIELD
    )
    INVALID_FIELD_FORMAT = AccessTokenResponse("4002401", DanaResponseMessage.INVALID_FIELD_FORMAT)


class DanaPaymentNotificationResponseCodeAndMessage:
    PaymentNotificationResponse = namedtuple('PaymentNotificationResponse', ['code', 'message'])

    SUCCESS = PaymentNotificationResponse("2005600", DanaResponseMessage.SUCCESSFUL)
    GENERAL_ERROR = PaymentNotificationResponse("5005600", DanaResponseMessage.GENERAL_ERROR)
    INTERNAL_SERVER = PaymentNotificationResponse("5005601", DanaResponseMessage.INTERNAL_SERVER)
    UNAUTHORIZED = PaymentNotificationResponse("4015600", DanaResponseMessage.UNAUTHORIZED)
    INVALID_TOKEN = PaymentNotificationResponse("4015601", DanaResponseMessage.INVALID_TOKEN)
    INVALID_MANDATORY_FIELD = PaymentNotificationResponse(
        "4005602", DanaResponseMessage.INVALID_MANDATORY_FIELD
    )
    INVALID_FIELD_FORMAT = PaymentNotificationResponse(
        "4005601", DanaResponseMessage.INVALID_FIELD_FORMAT
    )
    TRANSACTION_NOT_FOUND = PaymentNotificationResponse(
        "4045601", DanaResponseMessage.TRANSACTION_NOT_FOUND
    )


class DanaUnbindNotificationResponseCode:
    UnbindNotificationResponse = namedtuple(
        'UnbindNotificationResponse', ['code', 'result_code', 'message']
    )

    SUCCESS = UnbindNotificationResponse("00000000", "SUCCESS", "success")
    GENERAL_ERROR = UnbindNotificationResponse("00000019", "PROCESS_FAIL", "process fail")
    INTERNAL_SERVER = UnbindNotificationResponse("00000900", "SYSTEM_ERROR", "system error")


class ErrorDetail:
    NULL = 'This field may not be null.'
    BLANK = 'This field may not be blank.'
    REQUIRED = 'This field is required.'
    BLANK_LIST = 'This list may not be empty.'

    @classmethod
    def mandatory_field_errors(cls):
        return {cls.BLANK, cls.NULL, cls.REQUIRED, cls.BLANK_LIST}


class FeatureNameConst:
    SKIP_PROCESS_AUTH = 'dana_linking_skip_process_authentication'
