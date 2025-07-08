from juloserver.julo.exceptions import JuloException


class CreditCardNotFound(JuloException):
    pass


class FailedResponseBssApiError(JuloException):
    pass


class IncorrectOTP(JuloException):
    pass


class CreditCardApplicationNotFound(JuloException):
    pass


class CreditCardApplicationHasCardNumber(JuloException):
    pass


class CardNumberNotAvailable(JuloException):
    pass
