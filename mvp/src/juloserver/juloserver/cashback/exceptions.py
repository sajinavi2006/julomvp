from juloserver.julo.exceptions import JuloException


class CashbackException(JuloException):
    pass


class CashbackLessThanMinAmount(CashbackException):
    pass


class InvalidOverpaidStatus(JuloException):
    pass


class InvalidCashbackEarnedVerified(JuloException):
    pass
