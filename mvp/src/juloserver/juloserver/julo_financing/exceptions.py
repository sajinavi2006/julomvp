from juloserver.julo.exceptions import JuloException


class JFinancingException(JuloException):
    pass


class JFinancingProductLocked(JFinancingException):
    pass


class JuloException(Exception):
    pass


class JFinancingVerificationException(JuloException):
    pass


class LoanAmountExceedAvailableLimit(JFinancingVerificationException):
    pass


class CourierInfoIsEmpty(JFinancingVerificationException):
    pass


class WrongPathStatusChange(JFinancingVerificationException):
    pass


class CheckoutNotFound(JFinancingException):
    pass


class ProductOutOfStock(JFinancingException):
    pass


class UserNotAllowed(JFinancingException):
    pass


class InvalidVerificationStatus(JFinancingException):
    pass


class ProductNotFound(JFinancingException):
    pass
