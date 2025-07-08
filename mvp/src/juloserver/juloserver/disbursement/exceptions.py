from juloserver.loyalty.exceptions import GopayException


class DisbursementException(Exception):
    pass


class DisbursementServiceError(DisbursementException):
    pass


class BankNameNotFound(DisbursementServiceError):
    pass


class BcaApiError(DisbursementException):
    pass


class XenditApiError(DisbursementException):
    pass


class InstamoneyApiError(DisbursementException):
    pass


class XfersApiError(DisbursementException):
    def __init__(self, message, http_code=None):
        self.message = message
        self.http_code = http_code
        super().__init__(self.message)


class BcaServiceError(DisbursementException):
    pass


class XenditServiceError(DisbursementException):
    pass


class XfersServiceError(DisbursementException):
    pass


class GopayServiceError(DisbursementException, GopayException):
    pass


class GopayClientException(DisbursementException):
    pass


class GopayInsufficientError(DisbursementException, GopayException):
    pass


class XenditExperimentError(DisbursementException):
    pass


class XfersCallbackError(DisbursementException):
    pass


class AyoconnectCallbackError(DisbursementException):
    pass


class AyoconnectApiError(DisbursementException):
    def __init__(self, message, http_code=None, transaction_id=None, error_code=None):
        self.message = message
        self.http_code = http_code
        self.transaction_id = transaction_id
        self.error_code = error_code
        super().__init__(self.message)


class AyoconnectServiceError(DisbursementException):
    pass


class AyoconnectServiceForceSwitchToXfersError(AyoconnectServiceError):
    def __init__(self, message, error_code=None):
        self.message = message
        self.error_code = error_code
        super().__init__(self.message)


class PaymentGatewayApiError(DisbursementException):
    def __init__(self, message, http_code=None, transaction_id=None, error_code=None):
        self.message = message
        self.http_code = http_code
        self.transaction_id = transaction_id
        self.error_code = error_code
        super().__init__(self.message)


class PaymentGatewayAPIInternalError(DisbursementException):
    def __init__(self, message, http_code=None, transaction_id=None, error_code=None):
        self.message = message
        self.http_code = http_code
        self.transaction_id = transaction_id
        self.error_code = error_code
        super().__init__(self.message)
